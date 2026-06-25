#!/usr/bin/env python3
"""
GPIO Timing Accuracy Test for LuckFox Pico Max
Run as root: sudo python3 timing_test.py

Tests sleep() and Event.wait() accuracy without needing a scope —
compares requested vs measured wall-clock time for each toggle interval.
Also reports kernel HZ (timer tick resolution) and available clock info.
"""

import time
import threading
import os
import sys

# ── configuration ────────────────────────────────────────────────────────────
TEST_DURATIONS = [0.05, 0.1, 0.2, 0.5, 1.0, 2.0]   # seconds to test
REPEATS        = 5                                    # measurements per duration
# ─────────────────────────────────────────────────────────────────────────────


def get_kernel_hz():
    """Read CONFIG_HZ from /boot/config if available."""
    for path in ['/boot/config', f'/boot/config-{os.uname().release}']:
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith('CONFIG_HZ='):
                        return int(line.split('=')[1].strip())
        except Exception:
            pass
    return None


def get_timer_resolution():
    """Measure actual clock_gettime resolution."""
    # time.get_clock_info gives resolution for the monotonic clock
    info = time.get_clock_info('monotonic')
    return info.resolution


def measure_sleep(duration, repeats):
    """Measure time.sleep() accuracy."""
    errors = []
    for _ in range(repeats):
        t0 = time.monotonic()
        time.sleep(duration)
        elapsed = time.monotonic() - t0
        errors.append(elapsed - duration)
    return errors


def measure_event_wait(duration, repeats):
    """Measure threading.Event.wait(timeout=) accuracy."""
    errors = []
    for _ in range(repeats):
        ev = threading.Event()
        t0 = time.monotonic()
        ev.wait(timeout=duration)
        elapsed = time.monotonic() - t0
        errors.append(elapsed - duration)
    return errors


def stats(errors):
    n = len(errors)
    mean = sum(errors) / n
    variance = sum((e - mean) ** 2 for e in errors) / n
    stddev = variance ** 0.5
    return {
        'mean_ms':  mean   * 1000,
        'std_ms':   stddev * 1000,
        'min_ms':   min(errors) * 1000,
        'max_ms':   max(errors) * 1000,
    }


def print_table(title, results):
    print(f"\n{'─'*62}")
    print(f"  {title}")
    print(f"{'─'*62}")
    print(f"  {'Target':>8}  {'Mean err':>10}  {'Std':>8}  {'Min':>8}  {'Max':>8}")
    print(f"  {'(s)':>8}  {'(ms)':>10}  {'(ms)':>8}  {'(ms)':>8}  {'(ms)':>8}")
    print(f"{'─'*62}")
    for duration, s in results:
        sign = '+' if s['mean_ms'] >= 0 else ''
        print(f"  {duration:>8.3f}  "
              f"  {sign}{s['mean_ms']:>7.3f}  "
              f" {s['std_ms']:>7.3f}  "
              f" {s['min_ms']:>7.3f}  "
              f" {s['max_ms']:>7.3f}")
    print(f"{'─'*62}")


def main():
    print("\n╔══════════════════════════════════════════════════════════╗")
    print(  "║   LuckFox Pico Max — GPIO Timing Accuracy Test           ║")
    print(  "╚══════════════════════════════════════════════════════════╝")

    # System info
    hz = get_kernel_hz()
    res = get_timer_resolution()
    print(f"\n  Kernel CONFIG_HZ : {hz if hz else 'unknown (check /boot/config)'}")
    print(f"  Monotonic clock resolution : {res*1e6:.3f} µs")
    print(f"  Platform         : {os.uname().sysname} {os.uname().release} ({os.uname().machine})")
    print(f"  Python           : {sys.version.split()[0]}")
    print(f"  Repeats per duration : {REPEATS}")

    # time.sleep() test
    sleep_results = []
    print("\n  Measuring time.sleep() ...", flush=True)
    for d in TEST_DURATIONS:
        print(f"    {d:.3f} s × {REPEATS}...", end=' ', flush=True)
        errs = measure_sleep(d, REPEATS)
        s = stats(errs)
        sleep_results.append((d, s))
        print(f"mean err = {s['mean_ms']:+.3f} ms")

    # threading.Event.wait() test
    event_results = []
    print("\n  Measuring threading.Event.wait() ...", flush=True)
    for d in TEST_DURATIONS:
        print(f"    {d:.3f} s × {REPEATS}...", end=' ', flush=True)
        errs = measure_event_wait(d, REPEATS)
        s = stats(errs)
        event_results.append((d, s))
        print(f"mean err = {s['mean_ms']:+.3f} ms")

    print_table("time.sleep() — error vs requested duration", sleep_results)
    print_table("threading.Event.wait() — error vs requested duration", event_results)

    # Verdict
    print("\n  VERDICT")
    print(f"  {'─'*56}")
    worst_sleep = max(abs(s['mean_ms']) for _, s in sleep_results)
    worst_event = max(abs(s['mean_ms']) for _, s in event_results)
    print(f"  Worst mean overrun  →  sleep(): {worst_sleep:.2f} ms  |  "
          f"Event.wait(): {worst_event:.2f} ms")

    if hz and hz < 250:
        print(f"\n  ⚠  CONFIG_HZ={hz}: timer tick = {1000/hz:.1f} ms — "
              f"minimum sleep granularity is ~{1000/hz:.0f} ms.")
        print(f"     Sub-{1000/hz:.0f} ms pulse widths will be quantised to tick boundaries.")
    elif hz:
        print(f"\n  ✓  CONFIG_HZ={hz}: timer tick = {1000/hz:.2f} ms — "
              f"reasonable for lab timing.")

    print()


if __name__ == '__main__':
    main()
