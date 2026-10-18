"""LLM policy tweaks: per-repo lint/typecheck commands from Settings override defaults."""

from patchthecode.config import Settings
from patchthecode.validation.static import StaticValidator, default_commands


def test_from_settings_defaults_match_builtin():
    settings = Settings()
    validator = StaticValidator.from_settings(settings)
    assert validator.commands == default_commands()


def test_from_settings_lint_command_overrides_all_known_extensions():
    settings = Settings(_env_file=None)
    settings.lint_command = "my-linter --strict {file}"
    validator = StaticValidator.from_settings(settings)
    for ext in [".py", ".js", ".ts", ".tsx", ".go"]:
        assert validator.commands[ext] == ["my-linter", "--strict", "{file}"]


def test_from_settings_typecheck_command_overrides_python_only():
    settings = Settings(_env_file=None)
    settings.lint_command = "my-linter {file}"
    settings.typecheck_command = "pyright {file}"
    validator = StaticValidator.from_settings(settings)
    assert validator.commands[".py"] == ["pyright", "{file}"]
    assert validator.commands[".js"] == ["my-linter", "{file}"]


def test_agent_wires_settings_into_static_validator_by_default(tmp_path):
    from patchthecode.agent.orchestrator import Agent
    from patchthecode.storage.store import Store

    settings = Settings(_env_file=None)
    settings.lint_command = "lintx {file}"
    store = Store(tmp_path / "db.sqlite")
    agent = Agent(
        gateway=None,
        store=store,
        notifiers=[],
        settings=settings,
    )
    static = agent.validation.static
    assert static is not None
    assert static.commands[".py"] == ["lintx", "{file}"]


def test_generate_fix_prompt_includes_conventions_block():
    from patchthecode.llm.prompts import generate_fix_prompt

    msgs = generate_fix_prompt(
        {"repository": "r", "file_path": "a.py"},
        "x = 1",
        "bug",
        conventions="Use pathlib; never os.path",
    )
    assert "PROJECT CONVENTIONS" in msgs[0]["content"]
    assert "Use pathlib; never os.path" in msgs[0]["content"]


def test_fix_generator_passes_conventions_from_settings():
    from patchthecode.remediation.fixer import FixGenerator

    class _GW:
        async def complete_json(self, task, messages):
            return {"diff": "", "summary": "", "files": []}

    gen = FixGenerator(gateway=_GW(), conventions="Tabs not spaces")
    assert gen.conventions == "Tabs not spaces"
