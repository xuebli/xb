"""Click 帮助输出工具。"""

import inspect
import textwrap

import click
from rich.console import Console

HELP_CONTEXT = {"help_option_names": ["-h", "--help"]}
console = Console()


def _format_option_names(param: click.Option) -> str:
    names = sorted(
        [*param.opts, *param.secondary_opts],
        key=lambda name: (not name.startswith("-"), name.startswith("--"), name),
    )
    display = ", ".join(names)
    if not param.is_flag:
        metavar = param.metavar or param.name.upper()
        display = f"{display} {metavar}"
    return display


def _print_option(names: str, help_text: str, width: int) -> None:
    prefix = f"  {names:<{width}}  "
    wrapped = textwrap.wrap(
        help_text,
        width=76 - len(prefix),
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    console.print(f"  [cyan]{names:<{width}}[/cyan]  {wrapped[0]}")
    for line in wrapped[1:]:
        console.print(f"  {'':<{width}}  {line}")


class ChineseHelpCommand(click.Command):
    def get_help_option(self, ctx: click.Context) -> click.Option | None:
        help_options = self.get_help_option_names(ctx)
        if not help_options or not self.add_help_option:
            return None

        def show_help(ctx: click.Context, param: click.Parameter, value: bool) -> None:
            if value and not ctx.resilient_parsing:
                click.echo(ctx.get_help(), color=ctx.color)
                ctx.exit()

        return click.Option(
            help_options,
            is_flag=True,
            is_eager=True,
            expose_value=False,
            callback=show_help,
            help="显示帮助信息并退出。",
        )

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        command_parts = []
        current: click.Context | None = ctx
        while current is not None:
            if current.info_name:
                command_parts.append(current.info_name)
            current = current.parent
        command_path = " ".join(reversed(command_parts))
        usage = command_path
        usage_pieces = self.collect_usage_pieces(ctx)
        if usage_pieces:
            usage = f"{usage} {' '.join(usage_pieces)}"

        console.print(f"\n[bold green]Usage:[/bold green] [cyan]{usage}[/cyan]\n")

        help_text = inspect.cleandoc(self.help or "")
        if help_text:
            console.print(help_text)
            console.print()

        params = self.get_params(ctx)
        options = [param for param in params if isinstance(param, click.Option)]
        arguments = [param for param in params if isinstance(param, click.Argument)]

        if arguments:
            console.print("[bold green]Arguments:[/bold green]")
            for param in arguments:
                required = " [red]必填[/red]" if param.required else " [dim]可选[/dim]"
                console.print(f"  [cyan]{param.name}[/cyan]{required}")
            console.print()

        if options:
            console.print("[bold green]Options:[/bold green]")
            width = max(len(_format_option_names(param)) for param in options)
            for param in options:
                names = _format_option_names(param)
                help_text = param.help or ""
                _print_option(names, help_text, width)
            console.print()
