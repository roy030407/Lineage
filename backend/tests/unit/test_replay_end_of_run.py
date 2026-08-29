"""End-of-data behaviour.

Past the last telemetry row every station reads as RED (its last reading is
older than sensor_stale_after_s) and holds no car. Advancing into that
region reports a fabricated line-wide alarm, which is the same class of
untruth the "never report a fake safe value" invariant exists to prevent.
The clock stops at the last real frame instead.

This matters because the run is finite and playback is not: the committed
default run holds 9h 38m of simulated time, which is 9.6 minutes of wall
clock at 60x. Auto-play reaches the end during an ordinary demo.
"""

from datetime import timedelta

from lineage.config.specs import LineSpec
from lineage.datagen.models import RunConfig
from lineage.datagen.run import generate_run
from lineage.replay.engine import ReplayEngine
from lineage.replay.models import PlaybackMode
from lineage.replay.run_data import RunData


def _engine(tmp_path, line: LineSpec) -> ReplayEngine:
    config = RunConfig(
        run_id="end-of-run",
        random_seed=1,
        num_cars=3,
        background_defect_rate=0.0,
        baseline_temp_c=22.0,
        operator_profiles=[],
        operator_shift_schedule=[],
    )
    generate_run(line, config, output_root=tmp_path)
    run_data = RunData("end-of-run", tmp_path / "end-of-run")
    return ReplayEngine(line, run_data, start_time=run_data.start_time)


def test_run_data_exposes_an_end_time_at_or_after_start(tmp_path, tiny_line):
    engine = _engine(tmp_path, tiny_line)
    assert engine.run_data.end_time >= engine.run_data.start_time


def test_tick_past_the_end_clamps_the_clock_and_reports_ended(tmp_path, tiny_line):
    engine = _engine(tmp_path, tiny_line)
    end = engine.run_data.end_time

    engine.clock.seek(end + timedelta(seconds=1))
    state = engine.tick()

    assert state.playback_mode == PlaybackMode.ENDED
    assert engine.clock.current_time == end
    assert state.timestamp == end


def test_ended_clock_does_not_keep_advancing(tmp_path, tiny_line):
    engine = _engine(tmp_path, tiny_line)
    engine.clock.seek(engine.run_data.end_time + timedelta(seconds=1))
    engine.tick()

    first = engine.clock.current_time
    engine.tick()
    engine.tick()

    assert engine.clock.current_time == first


def test_a_tick_well_inside_the_run_does_not_end_it(tmp_path, tiny_line):
    """The clamp must fire at the end of the data and nowhere earlier."""
    engine = _engine(tmp_path, tiny_line)
    state = engine.tick()
    assert state.playback_mode == PlaybackMode.PLAYING


def test_play_after_end_restarts_from_the_beginning(tmp_path, tiny_line):
    """Resume on an ENDED run would otherwise be a no-op: the clock is
    already at the last frame, so the Play button would do nothing at all.
    """
    engine = _engine(tmp_path, tiny_line)
    engine.clock.seek(engine.run_data.end_time + timedelta(seconds=1))
    engine.tick()
    assert engine.clock.mode == PlaybackMode.ENDED

    engine.resume()

    assert engine.clock.mode == PlaybackMode.PLAYING
    assert engine.clock.current_time == engine.run_data.start_time


def test_pause_still_pauses_in_place_rather_than_rewinding(tmp_path, tiny_line):
    """Guards the resume() change from leaking into ordinary pause/resume:
    only ENDED rewinds, PAUSED must stay exactly where it was."""
    engine = _engine(tmp_path, tiny_line)
    engine.tick()
    engine.pause()
    paused_at = engine.clock.current_time

    engine.resume()

    assert engine.clock.mode == PlaybackMode.PLAYING
    assert engine.clock.current_time == paused_at
