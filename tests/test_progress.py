"""Deterministic contract tests for request progress events."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BUILD_MANAGER_ROOT = str(Path(__file__).resolve().parents[1])
if BUILD_MANAGER_ROOT not in sys.path:
    # Keep the suite's existing import precedence; this path is only a fallback
    # for running this test file directly from the repository root.
    sys.path.append(BUILD_MANAGER_ROOT)

from wwii_build.models import AttemptStatus, TaskState
from wwii_build.progress import (
    DEFAULT_HEARTBEAT_SECONDS,
    ErrorMetadata,
    LifecycleState,
    LocalizedMessage,
    ProgressConfig,
    ProgressConfigurationError,
    ProgressContractError,
    ProgressEvent,
    ProgressEventType,
    ProgressSnapshot,
    ProgressTracker,
    TerminalMetadata,
    WorkItemCounts,
    aggregate_counts,
    map_lifecycle_state,
)


UTC = dt.timezone.utc
START = dt.datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: dt.datetime = START) -> None:
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += dt.timedelta(seconds=seconds)


def message(text: str = "הבקשה התקבלה") -> LocalizedMessage:
    return LocalizedMessage(locale="he-IL", text=text, key="progress.synthetic",
                            parameters={"fixture": "synthetic"})


def tracker(clock: FakeClock, *, seconds: float = 30) -> ProgressTracker:
    return ProgressTracker(
        "request-synthetic-1", "run-synthetic-1", "task-synthetic-1",
        clock=clock, config=ProgressConfig(enabled=True, heartbeat_seconds=seconds),
    )


class SerializationTests(unittest.TestCase):
    def test_snapshot_and_event_round_trip_are_stable(self):
        terminal = TerminalMetadata(finished_at=START, reason="synthetic completion")
        snapshot = ProgressSnapshot(
            request_id="request-synthetic-1", run_id="run-synthetic-1", task_id="task-synthetic-1",
            sequence=8, lifecycle_state=LifecycleState.SUCCEEDED, current_phase="acceptance",
            current_task_label="synthetic contract tests", counts=WorkItemCounts(3, 3),
            message=message("הבדיקות הסתיימו"), event_timestamp=START,
            last_activity_timestamp=START, terminal=terminal,
        )
        encoded = snapshot.to_json()
        self.assertEqual(ProgressSnapshot.from_json(encoded), snapshot)
        self.assertEqual(json.loads(encoded)["work_items"]["percentage"], 100.0)
        event = ProgressEvent(ProgressEventType.TRANSITION, snapshot)
        self.assertEqual(ProgressEvent.from_json(event.to_json()), event)
        self.assertEqual(event.request_id, "request-synthetic-1")
        self.assertEqual(event.completed_work_items, 3)
        self.assertEqual(event.total_work_items, 3)
        self.assertFalse(event.indeterminate)
        self.assertIn('"event_type":"transition"', event.to_json())

    def test_serialization_rejects_derived_progress_disagreement(self):
        clock = FakeClock()
        accepted = tracker(clock).accept(
            current_phase="dispatch", current_task_label="synthetic request", message=message(),
            counts=WorkItemCounts(1, 2),
        )
        payload = accepted.to_dict()
        payload["work_items"]["percentage"] = 99
        with self.assertRaisesRegex(ProgressContractError, "percentage disagrees"):
            ProgressEvent.from_dict(payload)


class CountTests(unittest.TestCase):
    def test_aggregate_known_counts(self):
        aggregate = aggregate_counts([WorkItemCounts(1, 4), WorkItemCounts(2, 3)])
        self.assertEqual(aggregate, WorkItemCounts(3, 7))
        self.assertAlmostEqual(aggregate.percentage, 300 / 7)
        self.assertFalse(aggregate.indeterminate)

    def test_unknown_total_stays_indeterminate_and_has_no_percentage(self):
        aggregate = aggregate_counts([WorkItemCounts(2, 4), WorkItemCounts(3, None)])
        self.assertEqual(aggregate.completed, 5)
        self.assertIsNone(aggregate.total)
        self.assertTrue(aggregate.indeterminate)
        self.assertIsNone(aggregate.percentage)
        self.assertIsNone(aggregate.to_dict()["percentage"])

    def test_unknown_completed_count_is_not_inferred_as_zero(self):
        unknown = WorkItemCounts(total=4)
        self.assertIsNone(unknown.completed)
        self.assertTrue(unknown.indeterminate)
        self.assertIsNone(unknown.percentage)
        aggregate = aggregate_counts([WorkItemCounts(1, 2), unknown])
        self.assertIsNone(aggregate.completed)
        self.assertEqual(aggregate.total, 6)

    def test_counts_validate_their_domain(self):
        for args in ((-1, None), (2, 1), (True, 1), (0, -1)):
            with self.subTest(args=args), self.assertRaises(ProgressContractError):
                WorkItemCounts(*args)


class StateMappingTests(unittest.TestCase):
    def test_public_and_manager_states_have_explicit_lifecycle_mappings(self):
        expected = {
            "accepted": LifecycleState.ACCEPTED,
            "queued": LifecycleState.QUEUED,
            TaskState.RUNNING: LifecycleState.RUNNING,
            TaskState.WAITING_DEPENDENCY: LifecycleState.WAITING_DEPENDENCY,
            TaskState.BLOCKED: LifecycleState.WAITING_DEPENDENCY,
            TaskState.REVIEW_REQUIRED: LifecycleState.WAITING_DEPENDENCY,
            AttemptStatus.FAILED_ATTEMPT: LifecycleState.RETRYING,
            TaskState.REVIEWING: LifecycleState.TESTING,
            TaskState.PASSED: LifecycleState.SUCCEEDED,
            TaskState.FAILED: LifecycleState.FAILED,
            TaskState.CANCELLED: LifecycleState.CANCELLED,
        }
        for source, wanted in expected.items():
            with self.subTest(source=source):
                self.assertIs(map_lifecycle_state(source), wanted)

    def test_unknown_mapping_and_state_regression_are_rejected(self):
        with self.assertRaisesRegex(ProgressContractError, "unknown progress state"):
            map_lifecycle_state("synthetic_unknown")
        clock = FakeClock()
        progress = tracker(clock)
        progress.accept(current_phase="dispatch", current_task_label="synthetic", message=message())
        progress.transition(LifecycleState.RUNNING, current_phase="execute",
                            current_task_label="synthetic", message=message("רץ"))
        with self.assertRaisesRegex(ProgressContractError, "invalid lifecycle transition"):
            progress.transition(LifecycleState.ACCEPTED, current_phase="dispatch",
                                current_task_label="synthetic", message=message())


class EmissionTests(unittest.TestCase):
    def test_acceptance_is_immediate_and_material_transitions_are_ordered(self):
        clock = FakeClock()
        progress = tracker(clock)
        accepted = progress.accept(current_phase="dispatch", current_task_label="synthetic",
                                   message=message())
        self.assertEqual((accepted.event_type, accepted.sequence, accepted.event_timestamp),
                         (ProgressEventType.ACCEPTED, 1, START))
        clock.advance(1)
        queued = progress.transition(LifecycleState.QUEUED, current_phase="queue",
                                     current_task_label="synthetic", message=message("ממתין"))
        clock.advance(1)
        running = progress.transition(LifecycleState.RUNNING, current_phase="execute",
                                      current_task_label="synthetic unit", message=message("רץ"),
                                      counts=WorkItemCounts(1, 4))
        self.assertEqual((queued.sequence, running.sequence), (2, 3))
        self.assertEqual(running.last_activity_timestamp, clock.now)

    def test_heartbeat_uses_injected_cadence_and_deduplicates(self):
        clock = FakeClock()
        progress = tracker(clock)
        progress.accept(current_phase="dispatch", current_task_label="synthetic", message=message())
        progress.transition(LifecycleState.RUNNING, current_phase="execute",
                            current_task_label="synthetic", message=message("רץ"))
        clock.advance(29.999)
        self.assertIsNone(progress.heartbeat())
        before_sequence = progress.snapshot.sequence
        clock.advance(0.001)
        heartbeat = progress.heartbeat()
        self.assertEqual(heartbeat.event_type, ProgressEventType.HEARTBEAT)
        self.assertEqual(heartbeat.sequence, before_sequence + 1)
        self.assertIs(heartbeat.lifecycle_state, LifecycleState.RUNNING)
        self.assertEqual(heartbeat.event_timestamp, clock.now)
        self.assertIsNone(progress.heartbeat())
        self.assertEqual(progress.snapshot.sequence, heartbeat.sequence)

    def test_duplicate_transition_does_not_consume_sequence(self):
        clock = FakeClock()
        progress = tracker(clock)
        progress.accept(current_phase="dispatch", current_task_label="synthetic", message=message())
        clock.advance(1)
        first = progress.transition(LifecycleState.QUEUED, current_phase="queue",
                                    current_task_label="synthetic", message=message("ממתין"))
        clock.advance(10)
        duplicate = progress.transition(LifecycleState.QUEUED, current_phase="queue",
                                        current_task_label="synthetic", message=message("ממתין"))
        self.assertIsNone(duplicate)
        self.assertEqual(progress.snapshot.sequence, first.sequence)
        self.assertEqual(progress.snapshot.event_timestamp, first.event_timestamp)

    def test_non_running_and_terminal_states_suppress_heartbeats(self):
        clock = FakeClock()
        progress = tracker(clock)
        progress.accept(current_phase="dispatch", current_task_label="synthetic", message=message())
        clock.advance(30)
        self.assertIsNone(progress.heartbeat())
        progress.transition(LifecycleState.RUNNING, current_phase="execute",
                            current_task_label="synthetic", message=message("רץ"))
        clock.advance(1)
        terminal = progress.transition(
            LifecycleState.FAILED, current_phase="done", current_task_label="synthetic",
            message=message("נכשל"), error=ErrorMetadata("synthetic_error", "synthetic failure"),
            terminal_reason="synthetic test failure",
        )
        self.assertTrue(terminal.lifecycle_state.terminal)
        self.assertEqual(terminal.terminal.finished_at, clock.now)
        clock.advance(300)
        self.assertIsNone(progress.heartbeat())
        self.assertIsNone(progress.transition(
            LifecycleState.RUNNING, current_phase="execute", current_task_label="synthetic",
            message=message("לא אמור להיפלט"),
        ))
        self.assertEqual(progress.snapshot.sequence, terminal.sequence)

    def test_disabled_feature_flag_emits_nothing(self):
        clock = FakeClock()
        with mock.patch.dict(os.environ, {}, clear=True):
            progress = ProgressTracker("request", "run", "task", clock=clock)
            self.assertIsNone(progress.accept(current_phase="dispatch", current_task_label="synthetic",
                                              message=message()))
            self.assertIsNone(progress.heartbeat())

    def test_tracker_reads_the_feature_flag_when_config_is_omitted(self):
        clock = FakeClock()
        with mock.patch.dict(os.environ, {"WWII_BUILD_PROGRESS_UPDATES": "true"}, clear=True):
            progress = ProgressTracker("request", "run", "task", clock=clock)
            accepted = progress.accept(current_phase="dispatch", current_task_label="synthetic",
                                       message=message())
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted.sequence, 1)


class ConfigurationTests(unittest.TestCase):
    def test_defaults_are_disabled_with_thirty_second_heartbeat(self):
        config = ProgressConfig.from_env({})
        self.assertFalse(config.enabled)
        self.assertEqual(config.heartbeat_seconds, DEFAULT_HEARTBEAT_SECONDS)
        self.assertEqual(config.heartbeat_seconds, 30.0)

    def test_environment_configuration_is_parsed(self):
        config = ProgressConfig.from_env({
            "WWII_BUILD_PROGRESS_UPDATES": "yes",
            "WWII_BUILD_PROGRESS_HEARTBEAT_SECONDS": "12.5",
        })
        self.assertTrue(config.enabled)
        self.assertEqual(config.heartbeat_seconds, 12.5)

    def test_invalid_configuration_is_rejected(self):
        invalid_envs = [
            {"WWII_BUILD_PROGRESS_UPDATES": "sometimes"},
            {"WWII_BUILD_PROGRESS_HEARTBEAT_SECONDS": "0"},
            {"WWII_BUILD_PROGRESS_HEARTBEAT_SECONDS": "-1"},
            {"WWII_BUILD_PROGRESS_HEARTBEAT_SECONDS": "nan"},
            {"WWII_BUILD_PROGRESS_HEARTBEAT_SECONDS": "forever"},
        ]
        for env in invalid_envs:
            with self.subTest(env=env), self.assertRaises(ProgressConfigurationError):
                ProgressConfig.from_env(env)


if __name__ == "__main__":
    unittest.main()
