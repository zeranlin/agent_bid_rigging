from __future__ import annotations

import json
import shlex

import click

from agent_bid_rigging.core.runner import run_review


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
    )
    if ctx.obj.get("json_output") or json_flag or json_flag_compat:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    click.echo(f"已完成审查，供应商数: {len(report['suppliers'])}")
    for item in report["pairwise_assessments"]:
        click.echo(
            f"- {item['supplier_a']} vs {item['supplier_b']}: {item['risk_level']} ({item['risk_score']})"
        )


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
