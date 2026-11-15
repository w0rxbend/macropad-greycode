# greycode: `just` lists the recipes.

root := justfile_directory()
qmk := root / ".build/vial-qmk"
# vial-qmk commit the firmware was last built and checked against
qmk_rev := "dd43959ae5c08d8a28d38a1acf7b04e86b14a344"
qmk_image := "ghcr.io/qmk/qmk_cli:latest"

default:
    @just --list

# Everything quick without hardware or Docker (firmware link, greyd, configurator, FreeCAD add-on, PCB generator, pins)
test: test-firmware test-host test-configurator test-freecad pcb-test check

test-firmware:
    mkdir -p {{root}}/.build
    gcc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
        -I{{root}}/firmware/greycode -DVECTORS='"{{root}}/firmware/test/vectors.txt"' \
        {{root}}/firmware/greycode/hostlink.c {{root}}/firmware/test/test_hostlink.c \
        -o {{root}}/.build/test_hostlink
    {{root}}/.build/test_hostlink

test-host:
    cd {{root}}/host && cargo test && cargo clippy --all-targets -- -D warnings && cargo fmt --check

check:
    python3 {{root}}/tools/check_pins.py

# Fetch vial-qmk at the pinned commit (about 1 GB with submodules)
qmk-setup:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -d "{{qmk}}" ]; then
        git clone https://github.com/vial-kb/vial-qmk "{{qmk}}"
    fi
    git -C "{{qmk}}" fetch --depth 1 origin {{qmk_rev}}
    git -C "{{qmk}}" checkout -q {{qmk_rev}}
    git -C "{{qmk}}" submodule update --init --recursive --depth 1
    mkdir -p "{{qmk}}/keyboards/worxbend"
    ln -sfn "{{root}}/firmware/greycode" "{{qmk}}/keyboards/worxbend/greycode"

# Build the Vial firmware in the QMK container -> firmware/dist/greycode_vial.uf2
firmware: check
    [ -d "{{qmk}}" ] || just qmk-setup
    docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -e QMK_USERSPACE= \
        -v "{{root}}:{{root}}" -w "{{qmk}}" {{qmk_image}} make worxbend/greycode:vial
    mkdir -p {{root}}/firmware/dist
    cp {{qmk}}/worxbend_greycode_vial.uf2 {{root}}/firmware/dist/greycode_vial.uf2

# Run greyd from the source tree with the example config
host-run:
    cd {{root}}/host && cargo run --bin greyd -- config.example.toml

# Install greyd and greyctl to ~/.cargo/bin
host-install:
    cargo install --path {{root}}/host

test-configurator:
    cd {{root}}/configurator/core && cargo test && cargo clippy --all-targets -- -D warnings && cargo fmt --check
    cd {{root}}/configurator/ui && node --test test/

# FreeCAD add-on logic against a fake greyd (FreeCAD itself not needed)
test-freecad:
    cd {{root}} && python3 -B -m unittest discover -s freecad/tests

# Case: checks, STEP/STL exports, renders (needs cad/.venv, about 1 minute)
cad:
    cd {{root}} && cad/.venv/bin/python cad/build.py all

cad-check:
    cd {{root}} && cad/.venv/bin/python cad/build.py check

# PCB: schematic, placement, routing, DRC, contract, order files (KiCad 9.0.9 in Docker)
pcb:
    make -C {{root}}/pcb all

pcb-check:
    make -C {{root}}/pcb check

pcb-fab:
    make -C {{root}}/pcb fab

# PCB generator unit tests (no Docker)
pcb-test:
    make -C {{root}}/pcb test
