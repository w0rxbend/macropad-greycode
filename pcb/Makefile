# PCB tasks. Run from the repository root with `make -C pcb <target>`, or from here.
# Everything that needs KiCad runs in the pinned container through kicad.sh.
ROOT := $(abspath ..)
KICAD := $(ROOT)/pcb/kicad.sh
BOARD := pcb/kicad/greycode.kicad_pcb
BUILD := pcb/.build
FAB := pcb/fab
GERBER_LAYERS := F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts

.PHONY: help all place order check contract fab test repeat

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

all: place check fab test ## Rebuild the board, check it, write the order files, run the plain tests (Docker)

place: ## board.toml + gen/circuit.py -> schematic, placed and routed board, models, pictures; fails on an unrouted pad
	cd $(ROOT) && $(KICAD) python3 pcb/gen/build.py place
	cd $(ROOT) && python3 pcb/gen/circuit.py > pcb/netlist.txt

repeat: ## Run `place` twice and fail if the two board files differ (rebuilds must be byte-repeatable)
	mkdir -p $(ROOT)/$(BUILD)
	$(MAKE) -C $(ROOT)/pcb place
	cp $(ROOT)/$(BOARD) $(ROOT)/$(BUILD)/first.kicad_pcb
	$(MAKE) -C $(ROOT)/pcb place
	cmp $(ROOT)/$(BUILD)/first.kicad_pcb $(ROOT)/$(BOARD)
	sha256sum $(ROOT)/$(BOARD)

order: ## Search a routing order again (after moving parts or pins); rewrites gen/route_order.txt
	cd $(ROOT) && $(KICAD) python3 pcb/gen/build.py order

check: ## KiCad DRC against the schematic: fails on any error or unconnected item; then the board.toml contract
	mkdir -p $(ROOT)/$(BUILD)
	cd $(ROOT) && $(KICAD) kicad-cli pcb drc --severity-error --schematic-parity --exit-code-violations --format report -o $(BUILD)/drc.rpt $(BOARD)
	cd $(ROOT) && grep -E '^\*\* Found' $(BUILD)/drc.rpt
	cd $(ROOT) && $(KICAD) python3 pcb/gen/build.py contract

contract: ## The routed board against board.toml only
	cd $(ROOT) && $(KICAD) python3 pcb/gen/build.py contract

fab: ## Gerbers, drill files, JLCPCB BOM and placement list, board hash -> pcb/fab/, then a check that they agree
	mkdir -p $(ROOT)/$(FAB)/gerbers
	rm -f $(ROOT)/$(FAB)/gerbers/*
	cd $(ROOT) && $(KICAD) kicad-cli pcb export gerbers --layers $(GERBER_LAYERS) --subtract-soldermask -o $(FAB)/gerbers/ $(BOARD)
	cd $(ROOT) && $(KICAD) kicad-cli pcb export drill --format excellon --excellon-units mm --excellon-separate-th -o $(FAB)/gerbers/ $(BOARD)
	cd $(ROOT)/$(FAB) && rm -f greycode-gerbers.zip && zip -q -r greycode-gerbers.zip gerbers
	cd $(ROOT) && $(KICAD) python3 pcb/gen/build.py fab

test: ## Netlist self-check, router, schematic-writer, circuit and order-file tests (plain Python, no Docker)
	cd $(ROOT) && python3 pcb/gen/circuit.py > /dev/null
	cd $(ROOT) && python3 -m unittest discover -s pcb/gen -p 'test_*.py'
