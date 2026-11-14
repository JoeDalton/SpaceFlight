"""
Unit tests for the hyperspace jump sounds (space_flight.fx.hyperspace_sound).
"""

import pytest
from hyperspace_fakes import make_fake_sound

from space_flight.fx.hyperspace_sound import (
    ABORT_CROSS_FADE_S,
    ABORT_SOUND_VOLUME,
    JUMP_SOUND_VOLUME,
)

DT = 1 / 60


def run(sound, seconds: float):
    for _ in range(round(seconds / DT)):
        sound.update(DT)


def test_jump_plays_the_jump_sound_alone():
    sound = make_fake_sound()

    sound.jump()

    assert sound.jump_sound.playing
    assert sound.jump_sound.volume == JUMP_SOUND_VOLUME
    assert not sound.abort_sound.playing


def test_abort_cross_fades_the_jump_into_the_abort_sound():
    sound = make_fake_sound()
    sound.jump()

    sound.abort()
    assert sound.abort_sound.playing
    assert sound.abort_sound.volume == 0.0

    run(sound, ABORT_CROSS_FADE_S / 2)
    assert sound.jump_sound.volume == pytest.approx(JUMP_SOUND_VOLUME / 2, abs=0.1)
    assert sound.abort_sound.volume == pytest.approx(ABORT_SOUND_VOLUME / 2, abs=0.1)

    run(sound, ABORT_CROSS_FADE_S)
    assert not sound.jump_sound.playing
    assert sound.abort_sound.playing
    assert sound.abort_sound.volume == ABORT_SOUND_VOLUME


def test_a_paused_cross_fade_holds():
    sound = make_fake_sound()
    sound.jump()
    sound.abort()
    run(sound, ABORT_CROSS_FADE_S / 2)
    volume = sound.jump_sound.volume

    sound.update(0.0)

    assert sound.jump_sound.volume == volume


def test_a_new_jump_cuts_the_abort_sound_and_restores_the_jump_volume():
    sound = make_fake_sound()
    sound.jump()
    sound.abort()
    run(sound, ABORT_CROSS_FADE_S / 2)

    sound.jump()
    run(sound, ABORT_CROSS_FADE_S)

    assert sound.jump_sound.playing
    assert sound.jump_sound.volume == JUMP_SOUND_VOLUME
    assert not sound.abort_sound.playing


def test_destroy_silences_and_releases_both_sounds():
    sound = make_fake_sound()
    jump_pool, abort_pool = sound._jump_pool, sound._abort_pool
    sound.jump()
    sound.abort()

    sound.destroy()

    assert not sound.jump_sound.playing
    assert not sound.abort_sound.playing
    assert not jump_pool.in_use
    assert not abort_pool.in_use
