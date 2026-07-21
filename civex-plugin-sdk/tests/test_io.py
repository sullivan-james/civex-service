import subprocess
import sys
import textwrap

import pytest

from civex_plugin_sdk.io import FrameReader, FrameWriter


def test_frame_writer_writes_one_json_line_per_frame():
    lines: list[str] = []
    writer = FrameWriter(lines.append)
    writer.send({"type": "log", "stream": "stdout", "text": "hi"})
    writer.send({"type": "result", "outputs": {}})
    assert lines == [
        '{"type":"log","stream":"stdout","text":"hi"}\n',
        '{"type":"result","outputs":{}}\n',
    ]


def test_frame_reader_parses_lines_and_skips_blank_ones():
    lines = [
        '{"type": "describe"}\n',
        "\n",
        "   \n",
        '{"type": "run", "inputs": {}, "config": {}}\n',
    ]
    reader = FrameReader(lines)
    frames = list(reader)
    assert frames == [
        {"type": "describe"},
        {"type": "run", "inputs": {}, "config": {}},
    ]


def test_frame_reader_raises_stop_iteration_when_exhausted():
    reader = FrameReader([])
    with pytest.raises(StopIteration):
        next(reader)


def test_isolate_stdout_redirects_public_fd1_to_devnull_in_a_subprocess(
    tmp_path,
):
    """Exercises the real fd-dup trick across a genuine process boundary
    (safer than mutating fd 1 inside the pytest process itself, and it's
    exactly the boundary the trick is designed for)."""
    script = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, {src!r})
        from civex_plugin_sdk.io import isolate_stdout, FrameWriter

        out = isolate_stdout()
        print("this should not reach the parent's stdout")
        writer = FrameWriter.for_stream(out)
        writer.send({{"type": "log", "stream": "stdout", "text": "frame"}})
        """
    ).format(src=str((__import__("pathlib").Path(__file__).parents[1] / "src")))

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines == ['{"type":"log","stream":"stdout","text":"frame"}']
    assert "this should not reach" not in result.stdout
