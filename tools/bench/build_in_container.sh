#!/usr/bin/env bash
# Baut alle Benchmark-ELFs fuer thesis/messplan.md. Laeuft IM Container
# (ubuntu:24.04, weil der Poison-clang glibc >= 2.39 braucht); Aufruf ueber
# tools/bench/build.sh.
#
# Matrix: Workload x Opt-Stufe (O0, O2) x Variante (plain, poison) x Plattform
#   plain  = ohne -mllvm -riscv-stack-poison
#   poison = mit
#   htif   = Pfad 1, Standalone-Pydrofoil (crt.S + support/platform.c, HTIF)
#   vp     = Pfad 2, sysc_vp (crt.S + support/platform.c, UART + simdev)
#
# Grundsaetze (messplan.md):
# - Instrumentiert und mit der Opt-Stufe variiert wird NUR Workload-Code.
#   Harness, Startup und newlib (vorkompiliert mit GCC) bleiben immer gleich
#   (-O2, ohne Poison). Das entspricht dem realen Einsatz: libc wird nicht neu
#   gebaut. Der Harness ist in beiden Pfaden identisch bis auf das Backend fuer
#   Zeichenausgabe und Programmende (support/platform.c).
# - Ein Workload-Objekt wird einmal gebaut und fuer beide Plattformen gelinkt,
#   der Workload-Code ist damit pfaduebergreifend bitidentisch.
# - Ein fehlschlagender Workload bricht den Build nicht ab (status im Manifest).
#
# Mounts (von build.sh gesetzt):
#   /llvm  Poison-LLVM (ro)    /sdk  Zephyr-SDK riscv64-zephyr-elf (ro)
#   /bm    Pydrofoil-RISCV-benchmarks/baremetal (ro)
#   /repo  dieses Repo (rw, Ausgabe nach results/bench/)
#
# Umgebung:
#   GSF          Embench Global Scale Factor        (Default 1 = Kalibrierbuild)
#   WARMUP_HEAT  Embench Warmup-Iterationen         (Default 1 = Embench-Default)
#   MICRO_SCALE  Laufzeitfaktor der Mikrobenchmarks (Default 1 = Kalibrierbuild)
#   ONLY         Regex auf die Workload-ID, baut nur Treffer (Default: alles)
#   SCALE_FILE   Skalierung pro Workload (Pfad relativ zum Repo), TSV
#                "<workload-basis-id>[__<opt>]<TAB><faktor>", z.B.
#                "embench__crc32__O2<TAB>40" oder "micro__frame_size__FRAME256<TAB>5".
#                Gesucht wird zuerst mit, dann ohne __<opt>. Bei Embench
#                ersetzt der Faktor den GSF, bei Mikrobenchmarks MICRO_SCALE;
#                nicht gelistete Workloads nehmen GSF bzw. MICRO_SCALE.
#                riscv-tests sind nicht skalierbar.

set -uo pipefail

GSF="${GSF:-1}"
WARMUP_HEAT="${WARMUP_HEAT:-1}"
MICRO_SCALE="${MICRO_SCALE:-1}"
ONLY="${ONLY:-.}"
SCALE_FILE="${SCALE_FILE:-}"

LLVM=/llvm/bin
CC="$LLVM/clang"
OBJDUMP="$LLVM/llvm-objdump"
SIZE="$LLVM/llvm-size"

SDK=/sdk
MULTILIB=rv64imafdc_zicsr_zifencei/lp64d/medany
LIBC_DIR="$SDK/riscv64-zephyr-elf/lib/$MULTILIB"
LIBGCC_DIR="$SDK/lib/gcc/riscv64-zephyr-elf/12.2.0/$MULTILIB"
NEWLIB_INC="$SDK/riscv64-zephyr-elf/include"

RT=/bm/riscv_tests
EMB=/bm/embench_iot
LDSCRIPT_SRC=/bm/embench_helper/test.ld
LDSCRIPT=/repo/results/bench/build/link.ld
NOSYS=/bm/embench_helper/nosys.c

BENCH=/repo/tools/bench
OUT=/repo/results/bench
OBJ="$OUT/build/obj"
ELF="$OUT/elf"
LOG="$OUT/build/log"
MANIFEST="$ELF/manifest.tsv"

# rv64gc wie in Ghinamis embench_build.sh, explizit ausgeschrieben.
TARGET=(--target=riscv64-unknown-elf -march=rv64imafdc_zicsr_zifencei
	-mabi=lp64d -mcmodel=medany)
BASE=("${TARGET[@]}" -isystem "$NEWLIB_INC" -fno-common -g0)
# clang >= 16 macht diese Diagnosen in C99+ zu Fehlern; die Suiten sind alt.
LENIENT=(-Wno-error=implicit-function-declaration -Wno-error=implicit-int
	-Wno-error=int-conversion -Wno-error=incompatible-pointer-types
	-Wno-unknown-attributes -Wno-ignored-optimization-argument)
POISON_FLAG=(-mllvm -riscv-stack-poison)
HARNESS_OPT=(-O2)

LDFLAGS=("${TARGET[@]}" -fuse-ld=lld -nostdlib -nostartfiles -static
	-T "$LDSCRIPT")
LIBS=(-L"$LIBC_DIR" -L"$LIBGCC_DIR" -Wl,--start-group -lc -lm -lgcc
	-Wl,--end-group)

OPTS=(O0 O2)
VARIANTS=(plain poison)
PLATFORMS=(htif vp)

mkdir -p "$OBJ" "$LOG" "$ELF/htif" "$ELF/vp"

# Linkerskript: Ghinamis test.ld mit einer einzigen Aenderung fuer lld.
# lld kennt die Namen in PHDRS FLAGS(SHF_ALLOC | SHF_EXECINSTR) nicht; GNU ld
# setzt dafuer 0x2 | 0x4 = 6 ein (als Segment-Flags PF_W|PF_R). FLAGS(6) ist
# also exakt das, was GNU ld aus dem Original macht.
sed 's/FLAGS(SHF_ALLOC | SHF_EXECINSTR)/FLAGS(6)/' "$LDSCRIPT_SRC" >"$LDSCRIPT"
grep -q 'FLAGS(6)' "$LDSCRIPT" || { echo "FEHLER: test.ld-Anpassung griff nicht" >&2; exit 1; }

die() { echo "FEHLER: $*" >&2; exit 1; }

[[ -x "$CC" ]] || die "clang nicht gefunden unter $CC"
[[ -f "$LIBC_DIR/libc.a" ]] || die "newlib fehlt: $LIBC_DIR"
[[ -f "$LIBGCC_DIR/libgcc.a" ]] || die "libgcc fehlt: $LIBGCC_DIR"
[[ -f "$RT/benchmarks/common/crt.S" ]] || die "riscv-tests fehlt (Submodule?)"
[[ -f "$EMB/support/main.c" ]] || die "embench fehlt (Submodule?)"

#----------------------------------------------------------------------------
# Harness-Objekte (einmal, -O2, ohne Poison)
#----------------------------------------------------------------------------

H="$OBJ/harness"
mkdir -p "$H"

# clang-compat zuerst: ersetzt stdatomic.h fuer util.h (s. dortigen Kommentar)
RT_INC=(-I"$BENCH/support/clang-compat" -I"$RT/env" -I"$RT/benchmarks/common")

hcc() { # <out.o> <src> [flags...]
	local out=$1 src=$2; shift 2
	"$CC" "${BASE[@]}" "${HARNESS_OPT[@]}" "${LENIENT[@]}" "$@" \
		-c "$src" -o "$out" 2>>"$LOG/harness.log" \
		|| die "Harness-Objekt $out (s. $LOG/harness.log)"
}

: >"$LOG/harness.log"
hcc "$H/bench.o"       "$BENCH/support/bench.c"       -I"$BENCH/support"
hcc "$H/trap_report.o" "$BENCH/support/trap_report.c" -I"$BENCH/support"
hcc "$H/crt.o"         "$RT/benchmarks/common/crt.S"  "${RT_INC[@]}"
hcc "$H/nosys.o"       "$NOSYS"
# Plattformschicht statt riscv-tests' syscalls.c (Begruendung in platform.c:
# dessen printf nutzt den HTIF-Syscall-Proxy, den das Sail-Modell nicht kann).
hcc "$H/platform_htif.o" "$BENCH/support/platform.c" -I"$BENCH/support" -DBENCH_PLATFORM_HTIF
hcc "$H/platform_vp.o"   "$BENCH/support/platform.c" -I"$BENCH/support" -DBENCH_PLATFORM_VP

# Embench-Harness: main.c/beebsc.c aus der Suite, Board von uns
EMB_DEFS=(-DGLOBAL_SCALE_FACTOR="$GSF" -DWARMUP_HEAT="$WARMUP_HEAT")
EMB_INC=(-I"$EMB/support" -I"$BENCH/support/embench_board" -I"$BENCH/support")
hcc "$H/emb_main.o"   "$EMB/support/main.c"   "${EMB_INC[@]}" "${EMB_DEFS[@]}" -std=gnu17
hcc "$H/emb_beebsc.o" "$EMB/support/beebsc.c" "${EMB_INC[@]}" "${EMB_DEFS[@]}" -std=gnu17
hcc "$H/emb_board.o"  "$BENCH/support/embench_board/boardsupport.c" \
	"${EMB_INC[@]}" "${EMB_DEFS[@]}" -std=gnu17

PLATFORM_HTIF=("$H/crt.o" "$H/platform_htif.o" "$H/trap_report.o" "$H/bench.o" "$H/nosys.o")
PLATFORM_VP=("$H/crt.o" "$H/platform_vp.o" "$H/trap_report.o" "$H/bench.o" "$H/nosys.o")

declare -A SCALES=()
if [[ -n $SCALE_FILE ]]; then
	[[ -f /repo/$SCALE_FILE ]] || die "SCALE_FILE nicht gefunden: $SCALE_FILE"
	while IFS=$'\t' read -r key val _; do
		[[ -z $key || $key == \#* ]] && continue
		[[ $val =~ ^[0-9]+$ ]] || die "SCALE_FILE: ungueltiger Faktor fuer $key: '$val'"
		SCALES[$key]=$val
	done <"/repo/$SCALE_FILE"
	echo "Skalierung pro Workload aus $SCALE_FILE: ${#SCALES[@]} Eintraege"
fi
# Im Manifest je ELF protokolliert ("-" = nicht anwendbar).
CUR_GSF=- CUR_MSCALE=-

#----------------------------------------------------------------------------
# Manifest
#----------------------------------------------------------------------------

MANIFEST_HEADER="id	suite	workload	params	opt	variant	platform	status	elf	elf_sha256	text	data	bss	mpoison_static	functions_total	functions_instrumented	gsf	warmup_heat	micro_scale"
# Teil-Build (ONLY): Eintraege der nicht neu gebauten Workloads behalten, sonst
# beschriebe das Manifest nur noch die Teilmenge.
KEEP=""
if [[ $ONLY != "." && -f $MANIFEST ]]; then
	KEEP="$(mktemp)"
	tail -n +2 "$MANIFEST" | while IFS= read -r line; do
		id=${line%%	*}
		base=${id%__*__*}
		[[ $base =~ $ONLY ]] || printf '%s\n' "$line"
	done >"$KEEP"
fi
printf '%s\n' "$MANIFEST_HEADER" >"$MANIFEST"
[[ -n $KEEP ]] && cat "$KEEP" >>"$MANIFEST" && rm -f "$KEEP"

# Funktionen gesamt / mit mpoison, nur ueber die Workload-Objekte.
# Lokale Labels (.Lpcrel_hi* aus auipc-Paaren bei -mcmodel=medany, -O0) und
# Mapping-Symbole ($x/$d) erscheinen ebenfalls als Kopfzeilen, sind aber keine
# Funktionen und werden uebersprungen.
count_functions() { # <obj...>
	"$OBJDUMP" -d --no-show-raw-insn "$@" 2>/dev/null | awk '
		/^[0-9a-f]+ <[.$][^>]*>:$/ { next }
		/^[0-9a-f]+ <[^>]+>:$/ { if (fn != "") { tot++; if (hit) ins++ } fn = $2; hit = 0; next }
		/\tmpoison\t/ { hit = 1 }
		END { if (fn != "") { tot++; if (hit) ins++ } printf "%d\t%d\n", tot + 0, ins + 0 }'
}

record() { # <id> <suite> <workload> <params> <opt> <variant> <platform> <status> <elf> <wl-objs...>
	local id=$1 suite=$2 wl=$3 params=$4 opt=$5 var=$6 plat=$7 status=$8 elf=$9
	shift 9
	local sha="" text="" data="" bss="" mp="" fn_tot="" fn_ins=""
	if [[ $status == ok ]]; then
		sha=$(sha256sum "$elf" | cut -d' ' -f1)
		read -r text data bss _ < <("$SIZE" "$elf" | awk 'NR == 2')
		mp=$("$OBJDUMP" -d --no-show-raw-insn "$elf" | grep -c $'\tmpoison\t' || true)
		read -r fn_tot fn_ins < <(count_functions "$@")
	fi
	printf '%s\n' "$id	$suite	$wl	$params	$opt	$var	$plat	$status	${elf#/repo/}	$sha	$text	$data	$bss	$mp	$fn_tot	$fn_ins	$CUR_GSF	$WARMUP_HEAT	$CUR_MSCALE" >>"$MANIFEST"
}

#----------------------------------------------------------------------------
# Bauen
#----------------------------------------------------------------------------

n_ok=0
n_fail=0

# build_workload <suite> <workload> <params> <compile-flags-name> <harness-extra-name> <src...>
# compile-flags-name / harness-extra-name sind Namen von Bash-Arrays.
# SCALE_KIND (gsf|micro|none) waehlt, welches Makro die Skalierung erhaelt;
# der Faktor wird pro opt aufgeloest (SCALE_FILE).
build_workload() {
	local suite=$1 wl=$2 params=$3 cflags_name=$4 extra_name=$5
	shift 5
	local -n cflags=$cflags_name
	local -n extra=$extra_name
	local srcs=("$@")
	local base="${suite}__${wl}${params:+__$params}"

	[[ $base =~ $ONLY ]] || return 0

	for opt in "${OPTS[@]}"; do
		local sflags=() cur
		case $SCALE_KIND in
		gsf)
			cur=${SCALES[${base}__$opt]:-${SCALES[$base]:-$GSF}}
			CUR_GSF=$cur CUR_MSCALE=-
			sflags=(-DGLOBAL_SCALE_FACTOR="$cur")
			;;
		micro)
			cur=${SCALES[${base}__$opt]:-${SCALES[$base]:-$MICRO_SCALE}}
			CUR_GSF=- CUR_MSCALE=$cur
			sflags=(-DSCALE="$cur")
			;;
		*) CUR_GSF=- CUR_MSCALE=- ;;
		esac
		for var in "${VARIANTS[@]}"; do
			local id="${base}__${opt}__${var}"
			local odir="$OBJ/$id"
			local log="$LOG/$id.log"
			local vflags=()
			[[ $var == poison ]] && vflags=("${POISON_FLAG[@]}")
			mkdir -p "$odir"
			: >"$log"

			local objs=() ok=1
			for src in "${srcs[@]}"; do
				local o="$odir/$(basename "${src%.*}").o"
				if ! "$CC" "${BASE[@]}" "-$opt" "${vflags[@]}" "${LENIENT[@]}" \
					"${cflags[@]}" "${sflags[@]}" -c "$src" -o "$o" >>"$log" 2>&1; then
					ok=0
					break
				fi
				objs+=("$o")
			done

			for plat in "${PLATFORMS[@]}"; do
				local elf="$ELF/$plat/$id.elf"
				local pobjs
				if [[ $plat == htif ]]; then
					pobjs=("${PLATFORM_HTIF[@]}")
				else
					pobjs=("${PLATFORM_VP[@]}")
				fi
				rm -f "$elf"
				if ((ok)) && "$CC" "${LDFLAGS[@]}" "${pobjs[@]}" "${extra[@]}" \
					"${objs[@]}" "${LIBS[@]}" -o "$elf" >>"$log" 2>&1; then
					record "$id" "$suite" "$wl" "$params" "$opt" "$var" "$plat" ok "$elf" "${objs[@]}"
					((n_ok++))
				else
					record "$id" "$suite" "$wl" "$params" "$opt" "$var" "$plat" build_failed "$elf"
					((n_fail++))
					echo "  FEHLGESCHLAGEN: $id ($plat), s. ${log#/repo/}"
				fi
			done
		done
	done
	echo "  $base"
}

NO_EXTRA=()

# --- riscv-tests -----------------------------------------------------------
# mm fehlt bewusst: misst sich selbst ueber thread_entry/R Iterationen ohne
# setStats, passt nicht ins BENCH-Schema; matmult-int (Embench) deckt
# Matrixmultiplikation ab. mt-*/pmp/vec-*: s. messplan.md §6.2.
echo "== riscv-tests"
RT_WORKLOADS=(dhrystone median memcpy multiply qsort rsort spmv towers vvadd)
for b in "${RT_WORKLOADS[@]}"; do
	RT_CFLAGS=("${RT_INC[@]}" -I"$RT/benchmarks/$b" -std=gnu99 -ffast-math
		-fno-builtin-printf -DPREALLOCATE=1 -U_FORTIFY_SOURCE
		-DsetStats=bench_setStats)
	mapfile -t srcs < <(ls "$RT/benchmarks/$b"/*.c "$RT/benchmarks/$b"/*.S 2>/dev/null)
	SCALE_KIND=none
	build_workload riscv_tests "$b" "" RT_CFLAGS NO_EXTRA "${srcs[@]}"
done

# --- Embench-IoT -----------------------------------------------------------
echo "== embench (GSF=$GSF, WARMUP_HEAT=$WARMUP_HEAT)"
EMB_EXTRA=("$H/emb_main.o" "$H/emb_beebsc.o" "$H/emb_board.o")
for d in "$EMB"/src/*/; do
	b=$(basename "$d")
	SCALE_KIND=gsf
	EMB_CFLAGS=("${EMB_INC[@]}" -DWARMUP_HEAT="$WARMUP_HEAT" -std=gnu17 -fno-math-errno
		-fdata-sections -ffunction-sections)
	mapfile -t srcs < <(ls "$d"*.c)
	build_workload embench "$b" "" EMB_CFLAGS EMB_EXTRA "${srcs[@]}"
done

# --- Mikrobenchmarks ---------------------------------------------------------
echo "== micro (SCALE=$MICRO_SCALE)"
micro() { # <name> <params-id> [-DX=Y ...]
	local name=$1 pid=$2
	shift 2
	SCALE_KIND=micro
	MICRO_CFLAGS=(-I"$BENCH/support" -I"$BENCH/micro" -std=gnu11 "$@")
	build_workload micro "$name" "$pid" MICRO_CFLAGS NO_EXTRA "$BENCH/micro/$name.c"
}
for f in 16 64 256 1024 4096; do micro frame_size "FRAME$f" -DFRAME=$f; done
for w in 0 4 16 64 256;       do micro call_rate  "WORK$w"  -DWORK=$w;  done
for w in 1 8;                 do micro load_dense  "WIDTH$w" -DWIDTH=$w; done
for w in 1 8;                 do micro store_dense "WIDTH$w" -DWIDTH=$w; done
# DEPTH 512 * ~100-B-Frame bei -O0 bleibt unter den 128 KiB Stack aus crt.S
for d in 4 64 512;            do micro recurse "DEPTH$d" -DDEPTH=$d; done
micro baseline_alu ""

echo
echo "ok: $n_ok   fehlgeschlagen: $n_fail"
echo "Manifest: ${MANIFEST#/repo/}"
