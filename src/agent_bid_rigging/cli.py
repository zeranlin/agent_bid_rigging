from __future__ import annotations

import json
import shlex
from pathlib import Path

import click

from agent_bid_rigging.capabilities import CapabilityContext
from agent_bid_rigging.capabilities.ocr import OcrCapability
from agent_bid_rigging.capabilities.pdf_sectioning import PdfSectioningCapability
from agent_bid_rigging.core.runner import finish_llm_review, run_review
from agent_bid_rigging.web import run_demo_server


@click.group(invoke_without_command=True)
@click.option("--json-output", is_flag=True, help="Print machine-readable output.")
@click.pass_context
def cli(ctx: click.Context, json_output: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["json_output"] = json_output
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


@cli.command()
@click.option("--tender", required=True, type=click.Path(exists=True))
@click.option(
    "--bid",
    "bid_items",
    required=True,
    multiple=True,
    help="Supplier bid in the form supplier_name=/path/to/file",
)
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--label", default=None)
@click.option(
    "--opinion-mode",
    type=click.Choice(["auto", "template", "llm"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="How to generate the review opinion document.",
)
@click.option("--enable-ocr", is_flag=True, help="Enable OCR capability for PDFs and embedded images.")
@click.option("--json", "json_flag", is_flag=True, help="Print machine-readable output.")
@click.option("--json-output", "json_flag_compat", is_flag=True, help="Compatibility alias for --json.")
@click.pass_context
def analyze(
    ctx: click.Context,
    tender: str,
    bid_items: tuple[str, ...],
    output_dir: str | None,
    label: str | None,
    opinion_mode: str,
    enable_ocr: bool,
    json_flag: bool,
    json_flag_compat: bool,
) -> None:
    bids = _parse_bid_items(bid_items)
    report = run_review(
        tender,
        bids,
        output_dir=output_dir,
        label=label,
        opinion_mode=opinion_mode.lower(),
        enable_ocr=enable_ocr,
    )
    if ctx.obj.get("json_output") or json_flag or json_flag_compat:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    click.echo(f"已完成审查，供应商数: {len(report['suppliers'])}")
    for item in report["pairwise_assessments"]:
        click.echo(
            f"- {item['supplier_a']} vs {item['supplier_b']}: {item['risk_level']} ({item['risk_score']})"
        )


@cli.command("finish-llm")
@click.option("--run-dir", required=True, type=click.Path(exists=True))
@click.option("--json", "json_flag", is_flag=True, help="Print machine-readable output.")
@click.option("--json-output", "json_flag_compat", is_flag=True, help="Compatibility alias for --json.")
@click.pass_context
def finish_llm(
    ctx: click.Context,
    run_dir: str,
    json_flag: bool,
    json_flag_compat: bool,
) -> None:
    payload = finish_llm_review(run_dir)
    if ctx.obj.get("json_output") or json_flag or json_flag_compat:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"LLM 状态: {payload['state']}")


@cli.command("llm-status")
@click.option("--run-dir", required=True, type=click.Path(exists=True))
@click.option("--json", "json_flag", is_flag=True, help="Print machine-readable output.")
@click.option("--json-output", "json_flag_compat", is_flag=True, help="Compatibility alias for --json.")
@click.pass_context
def llm_status(
    ctx: click.Context,
    run_dir: str,
    json_flag: bool,
    json_flag_compat: bool,
) -> None:
    path = Path(run_dir) / "llm_status.json"
    if not path.exists():
        raise click.ClickException(f"Missing llm_status.json under {run_dir}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if ctx.obj.get("json_output") or json_flag or json_flag_compat:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"LLM 状态: {payload.get('state', 'unknown')}")


@cli.command("web-demo")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, type=int, show_default=True)
@click.option("--base-dir", type=click.Path(), default=None, help="Directory for uploaded files and run artifacts.")
def web_demo(host: str, port: int, base_dir: str | None) -> None:
    click.echo(f"启动演示页面: http://{host}:{port}")
    run_demo_server(host=host, port=port, base_dir=base_dir)


@cli.command("ocr")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True))
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--json", "json_flag", is_flag=True, help="Print machine-readable output.")
@click.option("--json-output", "json_flag_compat", is_flag=True, help="Compatibility alias for --json.")
@click.pass_context
def ocr(
    ctx: click.Context,
    input_path: str,
    output_dir: str | None,
    json_flag: bool,
    json_flag_compat: bool,
) -> None:
    capability = OcrCapability()
    result = capability.run(
        CapabilityContext(source_path=input_path),
        source_path=input_path,
        output_dir=output_dir,
    )
    payload = result.to_dict()
    if ctx.obj.get("json_output") or json_flag or json_flag_compat:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"OCR 完成，识别图片数: {payload['payload']['image_count']}")


@cli.command("pdf-sectioning")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True))
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--with-text/--without-text", default=True, show_default=True)
@click.option("--json", "json_flag", is_flag=True, help="Print machine-readable output.")
@click.option("--json-output", "json_flag_compat", is_flag=True, help="Compatibility alias for --json.")
@click.pass_context
def pdf_sectioning(
    ctx: click.Context,
    input_path: str,
    output_dir: str | None,
    with_text: bool,
    json_flag: bool,
    json_flag_compat: bool,
) -> None:
    capability = PdfSectioningCapability()
    result = capability.run(
        CapabilityContext(source_path=input_path),
        source_path=input_path,
        output_dir=output_dir,
        include_text=with_text,
    )
    payload = result.to_dict()
    if ctx.obj.get("json_output") or json_flag or json_flag_compat:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"PDF 章节切分完成，识别章节数: {payload['payload']['section_count']}")


@cli.command()
def repl() -> None:
    click.echo("进入围串标审查 REPL。输入 help 查看示例，输入 exit 退出。")
    while True:
        try:
            raw = click.prompt("bid-rigging", prompt_suffix="> ", default="", show_default=False)
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break

        line = raw.strip()
        if not line:
            continue
        if line in {"exit", "quit"}:
            break
        if line == "help":
            click.echo(
                "示例: analyze --tender 招标文件.zip "
                "--bid 供应商A=投标文件A.zip --bid 供应商B=投标文件B.zip "
                "--opinion-mode auto"
            )
            continue

        try:
            args = shlex.split(line)
            cli.main(args=args, prog_name="agent-bid-rigging", standalone_mode=False)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"执行失败: {exc}")


def _parse_bid_items(items: tuple[str, ...]) -> dict[str, str]:
    bids: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise click.BadParameter(f"Invalid --bid value: {item}")
        supplier, path = item.split("=", 1)
        supplier = supplier.strip()
        path = path.strip()
        if not supplier or not path:
            raise click.BadParameter(f"Invalid --bid value: {item}")
        bids[supplier] = path
    if len(bids) < 2:
        raise click.BadParameter("At least two supplier bids are required.")
    return bids


if __name__ == "__main__":
    cli()
