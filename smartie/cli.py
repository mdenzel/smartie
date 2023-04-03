import ctypes
import sys

import click
from rich import box
from rich.console import Console, Group, group
from rich.table import Table

from smartie.device import get_all_devices, get_device
from smartie.nvme import NVMEDevice
from smartie.scsi import SCSIDevice
from smartie.structures import c_uint128
from smartie.util import embed_bytes, grouper_it


@group()
def print_structure(structure: ctypes.Structure, *, indent=0):
    """
    Pretty prints a ctypes.Structure.
    """
    offset = 0

    t = Table(show_lines=True)
    t.add_column("Offset", style="white italic", justify="left")
    t.add_column("Name", style="magenta")
    t.add_column("Value")

    for field in structure._fields_:  # noqa
        if len(field) == 3:
            # If the field has a 3rd part, it's a bitfield, with the 3rd part
            # being the bit count.
            name, type_, bitcount = field
        else:
            name, type_ = field
            bitcount = ctypes.sizeof(type_) * 8

        value = getattr(structure, name)

        if isinstance(value, ctypes.Array):
            array_table = Table(show_header=False)
            array_table.add_column("Hex", no_wrap=True, style="green")
            array_table.add_column("ASCII", no_wrap=True, style="white")

            for chunk in grouper_it(20, bytearray(value)):
                chunk = list(chunk)

                array_table.add_row(
                    " ".join(f"{byte:02X}" for byte in chunk),
                    "".join(
                        chr(byte) if 32 <= byte <= 126 else "."
                        for byte in chunk
                    ),
                )

            t.add_row(
                f"[{offset:03}:{offset + bitcount:03}]", name, array_table
            )
        elif isinstance(value, c_uint128):
            t.add_row(
                f"[{offset:03}:{offset + bitcount:03}]",
                name,
                f"0x{int(value):03X}",
            )
        elif isinstance(value, ctypes.Structure):
            t.add_row(
                f"[{offset:03}:{offset + bitcount:03}]",
                name,
                Group(print_structure(value, indent=indent + 2)),
            )
        else:
            t.add_row(
                f"[{offset:03}:{offset + bitcount:03}]",
                name,
                f"0x{int(value):03X}",
            )

        offset += bitcount

    yield t


@click.group()
def cli():
    """
    Command line interface for SMARTie.
    """


@cli.command("enumerate")
def enumerate_command():
    """
    Enumerate all available devices, displaying basic information.
    """
    table = Table(box=box.SIMPLE)
    table.add_column("Path", style="magenta")
    table.add_column("Model", style="green")
    table.add_column("Serial", style="blue")
    table.add_column("Temperature")

    for device in get_all_devices():
        with device:
            table.add_row(
                device.path,
                device.model,
                device.serial,
                f"{device.temperature}",
            )

    console = Console()
    console.print(table)


@cli.command("details")
@click.argument("path")
def details_command(path: str):
    """
    Show detailed information for a specific device.
    """
    details_table = Table(show_header=False, box=box.SIMPLE)
    details_table.add_column("Key", style="magenta")
    details_table.add_column("Value", style="green")

    with get_device(path) as device:
        details_table.add_row("Model Number", device.model)
        details_table.add_row("Serial Number", device.serial)
        details_table.add_row("Temperature", f"{device.temperature}°C")

        smart_table = Table(
            title="SMART Attributes", title_style="magenta", box=box.SIMPLE
        )
        smart_table.add_column("ID", style="white")
        smart_table.add_column("Name", style="magenta")
        smart_table.add_column("Current", style="green", justify="right")
        smart_table.add_column("Worst", style="blue", justify="right")
        smart_table.add_column("Threshold", style="yellow", justify="right")
        smart_table.add_column("Unit", style="italic white")

        for entry in device.smart_table.values():
            smart_table.add_row(
                str(entry.id),
                entry.name,
                str(entry.current_value),
                str(entry.worst_value),
                str(entry.threshold),
                entry.unit.name,
            )

        details_table.add_row("", smart_table)

    console = Console()
    console.print(details_table)


@cli.command("debug")
@click.argument("path")
@click.argument(
    "command", type=click.Choice(["inquiry", "identify", "smart", "thresholds"])
)
@click.option(
    "--display",
    default="pretty",
    type=click.Choice(["pretty", "raw", "bytearray"]),
)
def debug_command(path: str, command: str, display: str = "pretty"):
    """
    Debug a device by sending a command and displaying the response as a raw
    structure.
    """
    console = Console()

    with get_device(path) as device:
        if isinstance(device, SCSIDevice):
            result = {
                "inquiry": device.inquiry,
                "identify": device.identify,
                "smart": device.smart,
                "thresholds": device.smart_thresholds,
            }.get(command)
            if result is None:
                console.print("Command unknown or unsupported by this device.")
                return

            structure = result()[0]
        elif isinstance(device, NVMEDevice):
            result = {"identify": device.identify, "smart": device.smart}.get(
                command
            )
            if result is None:
                console.print("Command unknown or unsupported by this device.")
                return

            structure = result()
        else:
            raise NotImplementedError("Unknown device type.")

        if display == "pretty":
            console.print(print_structure(structure))
        elif display == "raw":
            sys.stdout.buffer.write(bytes(structure))  # noqa
        elif display == "bytearray":
            print(embed_bytes(bytearray(structure)))  # noqa
