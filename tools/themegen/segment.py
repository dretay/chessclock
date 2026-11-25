#!/usr/bin/env python3
"""What each pixel of a picture is: sky, tree, building, water... (SegFormer-B2, trained on ADE20K's 150
kinds of thing), for the photo tools' "find automatically" (photo_scene.py): the sky, the water, where
windows can be (buildings and walls, not trees).

    tools/themegen/work/aienv/bin/python tools/themegen/segment.py PICTURE OUT.png OUT.json

OUT.png: each pixel's kind as a number (8-bit grey, the picture's size); OUT.json: {"labels": {number:
name}}. Runs in the AI environment (PyTorch, transformers: the one the castle's detail pass uses), on
the Mac's GPU when there is one: a few seconds; the model (about 100 MB) is downloaded once, from
Hugging Face. photo_scene.py runs this itself, and does without it if the environment isn't there.
"""
import json, sys

import torch
from PIL import Image
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

MODEL = "nvidia/segformer-b2-finetuned-ade-512-512"


def main():
    src, out_png, out_json = sys.argv[1:4]
    proc = SegformerImageProcessor.from_pretrained(MODEL)
    model = SegformerForSemanticSegmentation.from_pretrained(MODEL).eval()
    dev = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    model.to(dev)
    img = Image.open(src).convert("RGB")
    with torch.no_grad():
        logits = model(**proc(images=img, return_tensors="pt").to(dev)).logits
        up = torch.nn.functional.interpolate(logits, size=(img.height, img.width), mode="bilinear", align_corners=False)
        seg = up.argmax(1)[0].to(torch.uint8).cpu().numpy()
    Image.fromarray(seg, "L").save(out_png)
    json.dump({"labels": {int(k): v for k, v in model.config.id2label.items()}}, open(out_json, "w"))


if __name__ == "__main__":
    main()
