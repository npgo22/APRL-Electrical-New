#!/usr/bin/env python3
"""Write every board's lib tables and patch 3D model references.

Stock KiCad symbols, footprints and 3D models are not vendored: they come from
KiCad's own global tables and ${KICAD10_3DMODEL_DIR}, and boards embed every
symbol and footprint they place. Board lib tables list only the libraries in
kicadlibs/ (a project row would shadow the global library of the same name).

kicadlibs/models/ holds only models KiCad does not ship. Stock footprints that
KiCad ships without a model are pointed at ours (SUBSTITUTE), and models off the
footprint origin get their offset (MODEL_XFORM).

Idempotent: safe to re-run after a KiCad upgrade.
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Stock libraries come from the KiCad Flatpak's library runtimes
# (flatpak install --user flathub org.kicad.KiCad.Library.{Symbols,Footprints,Packages3D}).
FLATPAK = Path.home() / ".local/share/flatpak/runtime"
def _stock(runtime, sub):
    return FLATPAK / f"org.kicad.KiCad.Library.{runtime}/x86_64/stable/active/files/{sub}"
SYMBOLS = _stock("Symbols", "symbols")
FOOTPRINTS = _stock("Footprints", "footprints")
MODEL_DIRS = [_stock("Packages3D", "3dmodels")]
LIBS_DIR = "kicadlibs"          # repo-relative name of the library tree
LIBS = ROOT / LIBS_DIR
MODELS = LIBS / "models"
# Boards sit at varying depths, so paths go through the APRL_LIBS path
# variable (KiCad: Preferences > Configure Paths; CI: the workflow env) rather
# than counting "../" hops from KIPRJMOD.
VAR = "${APRL_LIBS}"

# KiCad ships these footprints but not their 3D models. Where we (or KiCad, for
# values with a "/") already carry the same manufacturer part, point at it; the rest stay dangling and are
# reported. Only exact part matches belong here -- a near-miss model renders a
# part that is not on the board, which is worse than no model at all.
SUBSTITUTE = {
    "Connector_RJ.3dshapes/RJ45_Hanrun_HR911105A_Horizontal.step": "RJ45-TH_HR911105A.step",
    "Connector_USB.3dshapes/USB_C_Receptacle_HRO_TYPE-C-31-M-12.step": "HRO_TYPE-C-31-M-12.step",
    "Fuse.3dshapes/FuseHolder_Blade_ATO_Littelfuse_FLR_178.6165.step": "178.6165.0001.step",
    "Package_DFN_QFN.3dshapes/DFN-8-1EP_3x2mm_P0.5mm_EP1.7x1.4mm.step": "DFN8_2x3MC_MCH.step",
    "Package_DFN_QFN.3dshapes/VQFN-24-1EP_4x4mm_P0.5mm_EP2.5x2.5mm.step":
        "Package_DFN_QFN.3dshapes/QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm.step",
    # KiCad's own model of the same body, terminals and pitch, differing only in
    # the exposed pad, which is hidden under the part.
    # TJA1462ATK (NXP SOT782-1): pad 0.05 mm narrower.
    "Package_SON.3dshapes/HVSON-8-1EP_3x3mm_P0.65mm_EP1.6x2.4mm.step":
        "Package_DFN_QFN.3dshapes/DFN-8-1EP_3x3mm_P0.65mm_EP1.55x2.4mm.step",
    # STM32H563RIVx (VFQFPN68): pad 5.2 mm, not 6.4.
    "Package_DFN_QFN.3dshapes/QFN-68-1EP_8x8mm_P0.4mm_EP6.4x6.4mm.step":
        "Package_DFN_QFN.3dshapes/QFN-68-1EP_8x8mm_P0.4mm_EP5.2x5.2mm.step",
    # ADS124S08 (VQFN-32 5x5): pad 3.3 mm, not 3.15.
    "Package_DFN_QFN.3dshapes/VQFN-32-1EP_5x5mm_P0.5mm_EP3.15x3.15mm.step":
        "Package_DFN_QFN.3dshapes/QFN-32-1EP_5x5mm_P0.5mm_EP3.3x3.3mm.step",
    # G-Switch GT-USB-7051A: KiCad ships the footprint but no model. This one is
    # the vendor's, fetched with JLC2KiCadLib and stripped of its LCSC logo.
    "Connector_USB.3dshapes/USB_C_Receptacle_G-Switch_GT-USB-7051x.step":
        "USB-C-SMD_GT-USB-7051A.step",
    # Also footprint-without-model, both fetched with JLC2KiCadLib.
    # Epson TG2520SMN 32 MHz (LCSC C6284791).
    "Oscillator.3dshapes/Oscillator_SMD_SeikoEpson_TG2520SMN-xxx-xxxxxx-4Pin_2.5x2.0mm.step":
        "OSC-SMD_4P-L2.5-W2.0-BL.step",
    # u-blox NEO-M8N (LCSC C6330769); matches the 24-pad NEO footprint.
    "RF_GPS.3dshapes/ublox_NEO.step": "GPSM-SMD_NEO-M8N.step",
}

# Models whose geometry does not sit on the footprint origin. Without these the
# part renders in the wrong place, and re-vendoring would silently undo a fix
# made by hand in the footprint. Millimetres, as KiCad's (offset (xyz ...)) wants.
MODEL_XFORM = {
    "USB-C-SMD_GT-USB-7051A.step": (0.0, 0.0, 5.775),
    "HRO_TYPE-C-31-M-12.step": (-4.475, -2.453, 0.0),
    # Model is centred on itself; the footprint origin is pin 1.
    "RJ45-TH_HR911105A.step": (4.44, -6.56, 0.0),
}

MODEL_REF = re.compile(r'\(model "\$\{KICAD10_3DMODEL_DIR\}/([^"]+)"')


# Directories that hold boards we do not maintain: archived designs, KiCad's
# generated template stub, and backup/history dumps.
SKIP = ("kicadlibs", "do-not-include", "-backups", ".history", "ali/v1", "ali/v2/default")


def boards():
    """Every live board, at whatever depth it sits."""
    return sorted({p.parent for p in ROOT.rglob("*.kicad_pro")
                   if not any(s in p.as_posix() for s in SKIP)})


def stock_names():
    """(footprint, symbol): names of the stock libraries KiCad's global tables provide."""
    return ({d.stem for d in FOOTPRINTS.glob("*.pretty")},
            {d.stem for d in SYMBOLS.glob("*.kicad_sym*")})


def uri_index():
    """(footprint, symbol): library name -> repo-relative path."""
    fp, sym = {}, {}
    for d in sorted(LIBS.glob("*/*.pretty")):
        fp[d.stem] = f"{LIBS_DIR}/{d.parent.name}/{d.name}"
    for d in sorted(LIBS.glob("*/*.kicad_symdir")):
        sym[d.stem] = f"{LIBS_DIR}/{d.parent.name}/{d.name}"
    for f in sorted(LIBS.glob("*/*.kicad_sym")):
        sym[f.stem] = f"{LIBS_DIR}/{f.parent.name}/{f.name}"
    return fp, sym


def model_targets():
    """Files whose model refs get patched: boards (which embed every placed
    footprint, stock ones included) and our own footprints."""
    targets = {f for b in boards() for f in b.glob("*.kicad_pcb") if "autosave" not in f.name}
    return sorted(targets | set(LIBS.rglob("*.kicad_mod")))


def repoint_models(targets):
    """Point stock refs KiCad ships no model for at a substitute, and fix offsets."""
    refs = set()
    for f in targets:
        refs |= set(MODEL_REF.findall(f.read_text(errors="replace")))

    dangling = []
    rename = {}
    for ref in sorted(refs):
        if any((d / ref).exists() for d in MODEL_DIRS):
            continue
        sub = SUBSTITUTE.get(ref, "")
        if "/" in sub and any((d / sub).exists() for d in MODEL_DIRS):
            rename[ref] = "${KICAD10_3DMODEL_DIR}/" + sub
        elif sub and (MODELS / sub).exists():
            rename[ref] = f"{VAR}/models/{sub}"
        else:
            dangling.append(ref)

    # Older boards and footprints counted "../" hops from KIPRJMOD; normalise
    # those to the path variable so a moved board heals itself on the next run.
    LEGACY = re.compile(r"\$\{KIPRJMOD\}/(?:\.\./)+" + LIBS_DIR + "/")

    changed = 0
    for f in targets:
        orig = f.read_text(errors="replace")
        t = LEGACY.sub(VAR + "/", orig)
        for ref, name in rename.items():
            t = t.replace(f'${{KICAD10_3DMODEL_DIR}}/{ref}', name)
        for name, xyz in MODEL_XFORM.items():
            t = re.sub(r'(\(model "[^"]*' + re.escape(name) + r'"\s*\(offset\s*\(xyz )[^)]*',
                       lambda m, v=xyz: m.group(1) + "%g %g %g" % v, t)
        if t != orig:
            f.write_text(t); changed += 1

    print(f"  models: {len(rename)} substituted, {changed} files repointed")
    for d in dangling:
        print(f"  DANGLING: KiCad ships no 3D model for {d}")


def update_tables():
    """Point every board's lib tables at every library in kicadlibs/.

    All boards get the same rows, so any house part can be placed on any board
    without editing a table first; stock parts come from the global tables.
    """
    fp_uri, sym_uri = uri_index()
    fp_stock, sym_stock = stock_names()
    for b in boards():
        for tbl, kind, pattern_glob, pattern, uri, stock in (
                ("fp-lib-table", "fp", "*.kicad_pcb", r'\(footprint "([^":]+):', fp_uri, fp_stock),
                ("sym-lib-table", "sym", "*.kicad_sch", r'\(lib_id "([^":]+):', sym_uri, sym_stock)):
            rows = "".join(
                f'\t(lib (name "{n}") (type "KiCad") '
                f'(uri "{VAR}/{p[len(LIBS_DIR) + 1:]}") (options "") (descr ""))\n'
                for n, p in sorted(uri.items()))
            # Rows for libraries that live with the board, not in kicadlibs/.
            if (b / tbl).exists():
                rows += "".join(l for l in (b / tbl).read_text().splitlines(keepends=True)
                                if "(lib " in l and VAR not in l)
            (b / tbl).write_text(f"({kind}_lib_table\n\t(version 7)\n{rows})\n")
            used = set()
            for f in b.glob(pattern_glob):
                used |= set(re.findall(pattern, f.read_text(errors="replace")))
            unknown = sorted(used - set(uri) - stock)
            if unknown:
                print(f"  WARN: {b.relative_to(ROOT)}/{tbl}: no library in {LIBS_DIR}/ or KiCad for {unknown}")


if __name__ == "__main__":
    missing = [d for d in (SYMBOLS, FOOTPRINTS, *MODEL_DIRS) if not d.is_dir()]
    if missing:
        sys.exit(f"KiCad library Flatpak not found: {missing[0]}")
    print("syncing libraries:")
    repoint_models(model_targets())
    update_tables()
    print("  lib tables updated")
