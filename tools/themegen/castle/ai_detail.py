"""A light AI detail pass over the castle renders (scene.py): photographic texture (stone, foliage,
flowers, sky) added by Stable Diffusion XL, image to image, held to the render's own outlines by a
ControlNet. Run locally on the Mac's GPU (Metal); nothing leaves the machine.

    tools/themegen/work/aienv/bin/python tools/themegen/castle/ai_detail.py [--looks day,dusk,night]
        [--strength 0.35] [--steps 30] [--seed 1234] [--cn 0.7]

Reads THEME_WORK/renders/LOOK.png (default tools/themegen/work/castle), writes THEME_WORK/ai/LOOK.png
(1344x800) and THEME_WORK/ai/edges.png. The day, dusk and night plates must stay aligned (the
screen fades between them, and the window and castle masks come from the renders), so every look
uses the day render's edges and the same seed, at a low strength: detail, not a new picture.

Models (downloaded once, into ~/.cache/huggingface): stabilityai/stable-diffusion-xl-base-1.0
(CreativeML Open RAIL++-M), diffusers/controlnet-canny-sdxl-1.0-small, and
madebyollin/sdxl-vae-fp16-fix (SDXL's VAE patched to run in half precision without NaNs).
Environment: python3 -m venv tools/themegen/work/aienv; aienv/bin/pip install torch diffusers
transformers accelerate safetensors pillow opencv-python-headless.
"""
import argparse, os, time
import cv2, numpy as np, torch
from PIL import Image
from diffusers import AutoencoderKL, ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
WORK = os.environ.get("THEME_WORK", os.path.join(REPO, "tools", "themegen", "work", "castle"))
W, H = 1344, 800                       # SDXL likes ~1 megapixel, multiples of 8; the screen's 5:3

# (CLIP reads at most 77 tokens: the light goes first, the place after, kept short)
PLACE = ("photo of Cinderella Castle, Magic Kingdom, from the hub: grey stone bastions, pink towers, "
         "blue turret roofs, gold spires, striped lawns, clipped hedges, lamp posts, sharp, detailed")
LIGHT = {
    "day": "sunny morning, blue sky, white clouds",
    "dusk": "blue hour twilight, deep blue sky, lights coming on",
    "night": "night, castle floodlit blue and pink, amber windows, moon, dark blue sky",
}
NEGATIVE = ("people, crowd, person, text, watermark, logo, signature, blurry, lowres, distorted, deformed, extra towers, "
            "cartoon, illustration, painting, cgi, 3d render, oversaturated, fireworks")


def edges(img):
    """The render's outlines (Canny), as the ControlNet wants them: white lines on black, RGB."""
    g = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    e = cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0), 60, 160)
    return Image.fromarray(np.stack([e] * 3, -1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--looks", default="day,dusk,night")
    ap.add_argument("--strength", type=float, default=0.35)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--cn", type=float, default=0.7, help="how hard the outlines hold")
    ap.add_argument("--guidance", type=float, default=6.0)
    ap.add_argument("--keep", action="store_true", help="leave the castle and lamps exactly as rendered (renders/keep.png)")
    a = ap.parse_args()
    out = os.path.join(WORK, "ai"); os.makedirs(out, exist_ok=True)
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    dt = torch.float16 if dev == "mps" else torch.float32

    t0 = time.time()
    cn = ControlNetModel.from_pretrained("diffusers/controlnet-canny-sdxl-1.0-small", torch_dtype=dt)
    vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=dt)
    pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0", controlnet=cn, vae=vae, torch_dtype=dt, variant="fp16", use_safetensors=True)
    pipe.to(dev); pipe.enable_attention_slicing()
    print("models loaded in %.0f s on %s" % (time.time() - t0, dev), flush=True)

    day = Image.open(os.path.join(WORK, "renders", "day.png")).convert("RGB").resize((W, H), Image.LANCZOS)
    guide = edges(day); guide.save(os.path.join(out, "edges.png"))
    for look in a.looks.split(","):
        src = Image.open(os.path.join(WORK, "renders", look + ".png")).convert("RGB").resize((W, H), Image.LANCZOS)
        g = torch.Generator("cpu").manual_seed(a.seed)                   # (the same noise for every look)
        t0 = time.time()
        img = pipe(prompt=LIGHT[look] + ", " + PLACE, negative_prompt=NEGATIVE, image=src, control_image=guide,
                   strength=a.strength, num_inference_steps=a.steps, guidance_scale=a.guidance,
                   controlnet_conditioning_scale=a.cn, generator=g, width=W, height=H).images[0]
        if a.keep:          # the castle and lamps straight from the render; the AI's everywhere else
            from PIL import ImageFilter
            k = Image.open(os.path.join(WORK, "renders", "keep.png")).convert("L").resize((W, H), Image.LANCZOS)
            k = k.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.2))   # (a hair over the edge, feathered)
            img = Image.composite(src, img, k)
        img.save(os.path.join(out, look + ".png")); print("%s in %.0f s" % (look, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
