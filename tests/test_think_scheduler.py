import numpy as np
import pytest

from space_flight.ai.think_scheduler import THINK_SLOT_S, ThinkScheduler


@pytest.mark.parametrize("n_bots", [1, 5, 6, 7, 21, 40])
def test_load_is_balanced_for_one_period(n_bots):
    scheduler = ThinkScheduler()
    for _ in range(n_bots):
        scheduler.register(period_s=0.1)
    loads = scheduler.load
    assert loads.sum() == n_bots
    assert loads.max() - loads.min() <= 1


def test_load_is_balanced_with_mixed_periods():
    """Fighters at 0.1 s (6 slots) and capital ships at 0.2 s (12 slots)."""
    scheduler = ThinkScheduler()
    for k in range(24):
        scheduler.register(period_s=0.2 if k % 8 == 0 else 0.1)
    loads = scheduler.load
    assert len(loads) == 12
    assert loads.max() - loads.min() <= 1


def test_load_stays_balanced_as_bots_die_and_spawn():
    rng = np.random.default_rng(0)
    scheduler = ThinkScheduler()
    slots = [scheduler.register(period_s=0.1) for _ in range(20)]
    for _ in range(200):
        dead = slots.pop(int(rng.integers(len(slots))))
        scheduler.unregister(dead)
        slots.append(scheduler.register(period_s=0.1))
        assert scheduler.load.max() - scheduler.load.min() <= 1
    for slot in slots:
        scheduler.unregister(slot)
    assert not scheduler.load.any()


def test_unregister_frees_exactly_the_slots_it_took():
    scheduler = ThinkScheduler()
    fighter = scheduler.register(period_s=0.1)
    capital = scheduler.register(period_s=0.2)
    scheduler.unregister(fighter)
    loads = scheduler.load
    assert loads.sum() == 1
    assert loads[capital.phase] == 1


def test_bot_thinks_once_per_period_on_its_phase():
    """Stepping a 60 Hz clock, a bot is due exactly on its own frames."""
    scheduler = ThinkScheduler()
    scheduler.register(period_s=0.1)  # takes phase 0
    slot = scheduler.register(period_s=0.1)  # least busy: another phase
    assert slot.phase != 0

    due_frames = []
    next_due_s = -np.inf
    now_s = 0.0
    for frame in range(60):
        if now_s >= next_due_s:
            due_frames.append(frame)
            next_due_s = slot.next_due_time_s(now_s)
        now_s += THINK_SLOT_S  # float accumulation, as the game clock does

    # First frame always thinks, then every 6 frames on the bot's phase
    assert due_frames[0] == 0
    assert due_frames[1:] == [f for f in range(1, 60) if f % 6 == slot.phase]


def test_a_long_frame_does_not_cause_a_burst_of_thinks():
    """After a lag spike, the next think is scheduled after now, not replayed."""
    scheduler = ThinkScheduler()
    slot = scheduler.register(period_s=0.1)
    due_s = slot.next_due_time_s(0.0)
    assert due_s == pytest.approx(0.1 - THINK_SLOT_S / 2)
    # One 0.5 s frame later: the next think is the first one after that time
    after_lag_s = slot.next_due_time_s(0.5)
    assert 0.5 < after_lag_s + THINK_SLOT_S / 2 <= 0.6 + 1e-9
