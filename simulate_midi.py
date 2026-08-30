#!/usr/bin/env python3
"""
MIDI Quantization Pipeline Simulator

Simulates MIDI note events at various tempos to test the quantization pipeline.
Run with: python3 simulate_midi.py [tempo] [notes]
"""

import sys
import time
sys.path.insert(0, '/home/pthag/ai/midi')

from monitor.state import State
from monitor.analysis import Analyser

def simulate_sequence(tempo_bpm, note_sequence, note_duration=0.3, note_gap=0.0, jitter=0.0):
    """
    Simulate a sequence of MIDI notes at a given tempo.
    
    Args:
        tempo_bpm: Target tempo in BPM
        note_sequence: List of MIDI note numbers
        note_duration: Duration of each note in seconds
        note_gap: Gap between notes in seconds
        jitter: Random timing jitter in seconds (e.g., 0.01 for ±10ms)
    """
    beat_duration = 60.0 / tempo_bpm
    interval = beat_duration + note_gap
    
    state = State()
    analyser = Analyser()
    base_time = time.time()
    
    print(f"\n{'='*60}")
    print(f"Simulating at {tempo_bpm} BPM")
    print(f"Beat duration: {beat_duration:.3f}s, interval: {interval:.3f}s")
    print(f"Note duration: {note_duration}s")
    print(f"{'='*60}")
    
    for i, note in enumerate(note_sequence):
        # Add jitter to timing
        jitter_offset = 0.0
        if jitter > 0:
            jitter_offset = (2.0 * (time.time() % 1.0) - 1.0) * jitter  # deterministic pseudo-random
        
        t = base_time + i * interval + jitter_offset
        
        # Note on
        event_on = {"type": "note_on", "note": note, "velocity": 64, "time": t}
        state.handle(event_on)
        analyser.on_note(t, note)
        
        # Note off after specified duration (with same jitter)
        t_off = t + note_duration + jitter_offset
        event_off = {"type": "note_off", "note": note, "time": t_off}
        state.handle(event_off)
        
        if state.quantized_notes:
            qn = state.quantized_notes[-1]
            note_name = f"{chr(65 + (note % 12))}{note//12 - 1}"
            print(f"  Note {note:3d} ({note_name:>3}): "
                  f"duration={qn['duration']:.3f}s, tempo={state.tempo_bpm:.1f} BPM")
    
    print(f"\nFinal tempo: {state.tempo_bpm:.1f} BPM")
    print(f"Quantized notes: {len(state.quantized_notes)}")
    return state

def run_tests():
    """Run multiple test scenarios"""
    
    # Test 1: Standard 120 BPM (quarter = 0.5s)
    print("\n" + "="*60)
    print("TEST 1: 120 BPM - Standard tempo")
    print("="*60)
    state1 = simulate_sequence(
        tempo_bpm=120,
        note_sequence=[60, 64, 67, 72, 76, 79, 84, 88, 91, 96, 98, 101],  # C major scale up, more notes
        note_duration=0.4  # quarter note at 120 BPM
    )
    
    # Test 2: 60 BPM (slow)
    print("\n" + "="*60)
    print("TEST 2: 60 BPM - Slow tempo")
    print("="*60)
    state2 = simulate_sequence(
        tempo_bpm=60,
        note_sequence=[60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 76, 74, 71, 69, 67, 65, 65, 67, 69, 72],  # C major scale up/down, more notes
        note_duration=0.8  # quarter note at 60 BPM
    )
    
    # Test 3: 180 BPM (fast)
    print("\n" + "="*60)
    print("TEST 3: 180 BPM - Fast tempo")
    print("="*60)
    state3 = simulate_sequence(
        tempo_bpm=180,
        note_sequence=[60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 76, 74, 71, 69, 67, 65, 65, 67, 69, 72, 74, 76, 76, 74, 71, 69, 67, 65, 65, 67, 69, 72],
        note_duration=0.15  # eighth note at 180 BPM
    )
    
    # Test 4: Chord sequence (block chords)
    print("\n" + "="*60)
    print("TEST 4: 120 BPM - Block chords")
    print("="*60)
    state4 = State()
    analyser = Analyser()
    base_time = time.time()
    chords = [[60, 64, 67], [65, 69, 72], [67, 71, 76], [60, 64, 67]]  # C, F, G, C
    for i, chord in enumerate(chords):
        t = base_time + i * 0.5
        # Note on for all notes in chord
        for note in chord:
            event_on = {"type": "note_on", "note": note, "velocity": 64, "time": t}
            state4.handle(event_on)
            analyser.on_note(t, note)
        # Note off
        t_off = t + 0.5
        for note in chord:
            event_off = {"type": "note_off", "note": note, "time": t_off}
            state4.handle(event_off)
    print(f"Final tempo: {state4.tempo_bpm:.1f} BPM")
    print(f"Quantized notes: {len(state4.quantized_notes)}")
    
    # Test 5: Arpeggio pattern
    print("\n" + "="*60)
    print("TEST 5: 120 BPM - Arpeggio pattern")
    print("="*60)
    state5 = simulate_sequence(
        tempo_bpm=120,
        note_sequence=[60, 64, 67, 72, 76, 72, 67, 64, 60, 64, 67, 72, 76, 72, 67, 64, 60, 64, 67, 72, 76, 72, 67, 64, 60],  # C major arpeggio up/down multiple times
        note_duration=0.2,  # eighth note at 120 BPM
        note_gap=0.05
    )

if __name__ == "__main__":
    run_tests()
    print("\n" + "="*60)
    print("ALL TESTS COMPLETED")
    print("="*60)

EOF