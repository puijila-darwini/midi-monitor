#!/usr/bin/env bash
# Live Fluidsynth local-synth sink for Abora (out box).
#
# FluidSynth's ALSA-seq driver shuts the synth down silently if stdin hits
# EOF (tested 2026-09-27: `/dev/null` stdin -> clean exit 0 right after the
# banner, no error). Keeping stdin attached to a pipe that never closes is
# what keeps the synth alive. `sleep infinity |` does exactly that.
set -e

# Ver 103: the AboraSynth card can pick any discovered soundfont — the chosen
# absolute path arrives as ABORA_SF2 from the launcher. Unset or missing =
# fall back to the first GM font found below (FluidR3_GM on this box).
SF2="${ABORA_SF2:-}"
if [ -z "$SF2" ] || [ ! -f "$SF2" ]; then
    SF2=""
    for p in \
        /usr/share/sounds/sf2/FluidR3_GM.sf2 \
        /usr/share/sounds/sf2/default-GM.sf2 \
        /usr/share/soundfonts/FluidR3_GM.sf2; do
        if [ -f "$p" ]; then SF2="$p"; break; fi
    done
fi
if [ -z "$SF2" ]; then
    echo "localsynth: no GM soundfont found" >&2
    exit 1
fi

exec sleep infinity | exec fluidsynth \
    -a pulseaudio \
    -m alsa_seq \
    -o midi.alsa_seq.id=AboraSynth \
    -g 0.8 \
    "$SF2"