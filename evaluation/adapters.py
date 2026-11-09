"""Adapter contracts and deterministic recordings. No network or credentials."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from .data import require, replay
import chess


@dataclass(frozen=True)
class Request:
    model: str
    parameters: dict
    prompt_revision: str
    context: dict
    max_cost: str
    currency: str


@dataclass(frozen=True)
class Response:
    text: str
    usage: dict
    latency_seconds: float


class TextProvider(Protocol):
    live: bool

    def respond(self, request: Request) -> Response: ...


class EngineProvider(Protocol):
    def analyze(self, position: dict, budget: dict) -> dict: ...


class RecordedText:
    """Replay a manually prepared ordered response tape (including billed failures)."""
    live = False

    def __init__(self, tape):
        self.tape = iter(deepcopy(tape))

    def respond(self, request):
        row = next(self.tape)
        if row.get('timeout'):
            raise TimeoutError('recorded uncertain provider outcome')
        return Response(row['text'], row['usage'], row['latency_seconds'])


class RecordedEngine:
    def __init__(self, records):
        self.records = deepcopy(records)

    def analyze(self, position, budget):
        fen = replay(position)
        record = self.records[fen]
        require(record['budget'] == budget, 'recorded engine budget mismatch')
        require(record['fen'] == fen, 'recorded engine position mismatch')
        # Only engine facts may cross the prompt boundary.
        facts = {field: deepcopy(record[field]) for field in
                 ('fen', 'budget', 'depth', 'nodes', 'time_seconds', 'lines')}
        for line in facts['lines']:
            board = chess.Board(fen)
            for move in line:
                board.push_uci(move)
        return facts
