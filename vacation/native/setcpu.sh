#!/bin/sh
# setcpu.sh MHZ: set the F1C100s/F1C200s CPU clock live (multiple of 24 MHz). Until the next reboot.
# PLL_CPU = 24 MHz x N (K=M=P=1). The CPU runs from the 24 MHz crystal while the PLL changes.
N=$(( $1 / 24 ))
devmem 0x01C20050 32 0x00010000                      # CPU clock source: 24 MHz crystal
devmem 0x01C20000 32 $(printf 0x%08X $(( 0x80000000 | ((N - 1) << 8) )))
i=0; while [ $(( $(devmem 0x01C20000) & 0x10000000 )) -eq 0 ] && [ $i -lt 1000 ]; do i=$((i+1)); done
devmem 0x01C20050 32 0x00020000                      # back to PLL_CPU
echo "cpu: $(( 24 * ((($(devmem 0x01C20000) >> 8) & 31) + 1) )) MHz"
