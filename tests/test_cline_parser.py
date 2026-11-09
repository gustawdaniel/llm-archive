import tempfile
import json
from pathlib import Path
from src.normalizers.cline import ClineNormalizer
from daemon.parsers.cline import ClineParser


def test_cline_normalizer_ui_messages():
    normalizer = ClineNormalizer()
    sample_ui_messages = [
        {
            "ts": 1727271234000,
            "type": "say",
            "say": "task",
            "text": "<task>\nUtwórz plik hello_cline.py\n</task>"
        },
        {
            "ts": 1727271235000,
            "type": "say",
            "say": "reasoning",
            "text": "Planuję utworzyć plik hello_cline.py z kodem print('Hello from Cline!')."
        },
        {
            "ts": 1727271236000,
            "type": "say",
            "say": "text",
            "text": "Tworzę plik hello_cline.py."
        },
        {
            "ts": 1727271237000,
            "type": "say",
            "say": "tool",
            "text": json.dumps({"tool": "newFileCreated", "path": "/home/user/project/hello_cline.py", "content": "print('Hello from Cline!')"})
        },
        {
            "ts": 1727271238000,
            "type": "ask",
            "ask": "command",
            "text": "python hello_cline.py"
        },
        {
            "ts": 1727271239000,
            "type": "say",
            "say": "command_output",
            "text": "Hello from Cline!\n"
        },
        {
            "ts": 1727271240000,
            "type": "say",
            "say": "completion_result",
            "text": "Gotowe! Plik został utworzony i przetestowany."
        }
    ]

    conv = normalizer.parse(sample_ui_messages, metadata={"task_id": "test-task-123", "device": "rog"})

    assert conv.platform == "cline"
    assert conv.external_id == "test-task-123"
    assert "Utwórz plik hello_cline.py" in conv.title
    assert conv.project_path == "/home/user/project/hello_cline.py" or "/home/user/project" in conv.project_path
    assert len(conv.messages) == 2  # 1 User message + 1 Assistant message with reasoning and tools

    user_msg = conv.messages[0]
    assert user_msg.role == "user"
    assert user_msg.content == "Utwórz plik hello_cline.py"

    asst_msg = conv.messages[1]
    assert asst_msg.role == "assistant"
    assert asst_msg.reasoning_content is not None
    assert "Planuję utworzyć" in asst_msg.reasoning_content
    assert "Tworzę plik hello_cline.py" in asst_msg.content
    assert len(asst_msg.tool_calls) == 2
    assert asst_msg.tool_calls[0].name == "newFileCreated"
    assert asst_msg.tool_calls[1].name == "execute_command"
    assert asst_msg.tool_calls[1].output == "Hello from Cline!\n"


def test_cline_normalizer_api_history():
    normalizer = ClineNormalizer()
    sample_api_history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "<task>\nNapisz funkcję fibonacci\n</task>"}
            ]
        },
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "text": "Zaimplementuję rekurencyjnie ze spamiętywaniem."},
                {"type": "text", "text": "Oto implementacja fibonacci:"},
                {
                    "type": "tool_use",
                    "id": "tool_call_1",
                    "name": "write_to_file",
                    "input": {"path": "fib.py", "content": "def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)"}
                }
            ]
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tool_call_1", "content": "Success"}
            ]
        }
    ]

    conv = normalizer.parse(sample_api_history, metadata={"task_id": "fib-task-456"})

    assert conv.platform == "cline"
    assert conv.external_id == "fib-task-456"
    assert "Napisz funkcję fibonacci" in conv.title
    assert len(conv.messages) == 2

    asst_msg = conv.messages[1]
    assert asst_msg.role == "assistant"
    assert asst_msg.reasoning_content == "Zaimplementuję rekurencyjnie ze spamiętywaniem."
    assert len(asst_msg.tool_calls) == 1
    assert asst_msg.tool_calls[0].output == "Success"


def test_cline_parser_directory():
    parser = ClineParser()
    with tempfile.TemporaryDirectory() as tmpdir:
        task_dir = Path(tmpdir) / "tasks" / "1790123456789_ab123"
        task_dir.mkdir(parents=True)

        ui_file = task_dir / "ui_messages.json"
        ui_file.write_text(json.dumps([
            {"ts": 1727271000000, "type": "say", "say": "task", "text": "Cześć Cline!"},
            {"ts": 1727271005000, "type": "say", "say": "text", "text": "Cześć! W czym mogę pomóc?"}
        ]), encoding="utf-8")

        meta_file = task_dir / "task_metadata.json"
        meta_file.write_text(json.dumps({
            "workspace": "/home/user/project",
            "model_usage": [{"model": "deepseek-v4.1-flash"}]
        }), encoding="utf-8")

        tasks = parser.scan_tasks(Path(tmpdir))
        assert len(tasks) == 1
        assert tasks[0] == ui_file

        conv = parser.parse_file(tasks[0])
        assert conv.platform == "cline"
        assert conv.external_id == "1790123456789_ab123"
        assert conv.title == "Cześć Cline!"
        assert conv.project_path == "/home/user/project"
        assert conv.model == "deepseek-v4.1-flash"
        assert len(conv.messages) == 2
