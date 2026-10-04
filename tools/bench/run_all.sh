#!/usr/bin/env bash
# Startet die Messreihen aus thesis/messplan.md §10 mit einem Befehl.
#
#   ./tools/bench/run_all.sh                 # Standard-Stufen, im Vordergrund
#   ./tools/bench/run_all.sh --detach        # losgeloest (setsid/nohup), ueberlebt Logout
#   ./tools/bench/run_all.sh timing-iss-O0   # nur bestimmte Stufen
#   ./tools/bench/run_all.sh --list          # Stufen anzeigen
#   ./tools/bench/run_all.sh --detach --wait # erst starten, wenn ein laufendes
#                                            # bench.py run fertig ist
#
# Jede Stufe ist ein bench.py-Aufruf und damit fortsetzbar: erledigte Laeufe
# (gleicher Simulator, gleiches ELF per SHA-256, gleiche Wiederholung) werden
# uebersprungen. Ein Abbruch (Neustart, kill) kostet nur den laufenden Lauf;
# denselben Befehl erneut starten.
#
# Voraussetzungen (README.md): ELFs gebaut (build.sh mit SCALE_FILE), alle
# Simulatoren im Repo-Root bzw. als Image vorhanden. Der Build ist bewusst
# keine Stufe: ein Neubau aendert die ELF-Hashes und damit die Zuordnung zu
# bereits gemessenen Laeufen.
#
# Log: results/bench/run_all.log (eine Zeile pro Stufenstart/-ende, die
# Ausgabe jeder Stufe darunter).

set -uo pipefail

# Gesamter Rumpf in einem Block: bash liest ihn vor der Ausfuehrung komplett
# ein. Ohne das liest eine laufende (z. B. mit --wait wartende) Instanz nach
# einer Aenderung dieser Datei an der alten Byte-Position weiter und bricht
# mit Syntaxfehler ab (so geschehen am 03.10.).
{

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1
BENCH=(python3.12 tools/bench/bench.py run)
LOG=results/bench/run_all.log
LOCK=results/bench/.run_all.lock

# VP-Auswahl: speicherlastig, Nutzungskosten, rechenlastig, mpoison isoliert
VP_MATCH='^(embench__(sglib-combined|slre|edn)|micro__frame_size__FRAME256)__'

# Stufe -> Befehl. Reihenfolge = Standardreihenfolge.
STAGE_NAMES=(count negctl timing-iss-O2 timing-csim-O2 timing-iss-O0 count-vp timing-vp)
DEFAULT_STAGES=(count negctl timing-iss-O2 timing-csim-O2)
declare -A STAGE_CMD=(
	# Instruktionszahlen A/B/C/Bo/Co, parallel (deterministisch)
	[count]="${BENCH[*]} --path iss --mode count --jobs 8 --timeout 600"
	# Negativkontrolle N (Sim ohne Poison, poison-ELF, erwartet mcause=2)
	[negctl]="${BENCH[*]} --path iss --mode negctl --jobs 8 --timeout 600"
	# Hauptmessung Pfad 1: A/A2/B/C/Bo/Co x 5, seriell, gepinnt, randomisiert
	[timing-iss-O2]="${BENCH[*]} --path iss --mode timing --opt O2 --reps 5"
	# C-Emulator: volle Laeufe dauern im Median 0,4 h (0,5 MIPS), daher
	# Zwei-Punkt-Messung N/2N = 1e7/2e7 Instruktionen (messplan.md §9.1);
	# kuerzestes Embench-ELF hat 3,2e7, 2N liegt also ueberall im Programm.
	[timing-csim-O2]="${BENCH[*]} --path csim --mode twopoint --inst-limit 10000000 --suite embench --opt O2 --reps 3"
	# -O0 abgespeckt (Entscheidung 04.10.): nur A/A2/Bo/Co. alt gegen opt ist
	# bei -O2 belegt; die Instruktionszahlen von B/C bei -O0 liefert count.
	# -O0 zeigt die Nutzungskosten (bei -O2 kaum mpoison in Embench). ~3 h.
	[timing-iss-O0]="${BENCH[*]} --path iss --mode timing --opt O0 --reps 5 --config A --config A2 --config Bo --config Co"
	# VP: ~2,3 MIPS (Probe md5sum B: 779 s gegen 17 s standalone), volle
	# Embench-Reihe waere ~28 h. Daher Auswahl mit denselben ELFs/Faktoren wie
	# Pfad 1 und 3 (Vergleichbarkeit), VP-A je ~1-2,5 min (messplan.md §12)
	[count-vp]="${BENCH[*]} --path vp --mode count --jobs 4 --opt O2 --match ${VP_MATCH} --timeout 3600"
	[timing-vp]="${BENCH[*]} --path vp --mode timing --opt O2 --match ${VP_MATCH} --reps 3 --timeout 3600"
)

usage() {
	sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
	exit "${1:-0}"
}

list_stages() {
	for s in "${STAGE_NAMES[@]}"; do
		local mark=" "
		[[ " ${DEFAULT_STAGES[*]} " == *" $s "* ]] && mark="*"
		printf '%s %-16s %s\n' "$mark" "$s" "${STAGE_CMD[$s]}"
	done
	echo "(* = Standard)"
}

DETACH=0
WAIT=0
STAGES=()
for a in "$@"; do
	case $a in
	--detach) DETACH=1 ;;
	--wait) WAIT=1 ;;
	--list) list_stages; exit 0 ;;
	-h | --help) usage ;;
	*)
		[[ -n ${STAGE_CMD[$a]:-} ]] || { echo "unbekannte Stufe: $a" >&2; list_stages >&2; exit 1; }
		STAGES+=("$a")
		;;
	esac
done
((${#STAGES[@]})) || STAGES=("${DEFAULT_STAGES[@]}")

mkdir -p results/bench

if ((DETACH)); then
	extra=()
	((WAIT)) && extra=(--wait)
	setsid nohup "$0" "${extra[@]}" "${STAGES[@]}" >>"$LOG" 2>&1 </dev/null &
	echo "losgeloest gestartet (PID $!), Log: $LOG"
	echo "Fortschritt: tail -f $LOG"
	exit 0
fi

# Nur eine Instanz; auch ein von Hand gestartetes bench.py run blockiert,
# weil parallele Laeufe die Zeitmessung verfaelschen.
exec 9>"$LOCK"
if ((WAIT)); then
	# mit --wait hinter einer laufenden Instanz einreihen
	flock -n 9 || { echo "=== $(date -Is) warte auf laufendes run_all.sh"; flock 9; }
else
	flock -n 9 || { echo "run_all.sh laeuft bereits ($LOCK)" >&2; exit 1; }
fi
BUSY='^python[0-9.]* tools/bench/bench.py run'
if ((WAIT)) && pgrep -u "$USER" -f "$BUSY" >/dev/null; then
	echo "=== $(date -Is) warte auf laufendes bench.py run:"
	pgrep -a -u "$USER" -f "$BUSY"
	while pgrep -u "$USER" -f "$BUSY" >/dev/null; do sleep 60; done
	echo "=== $(date -Is) bench.py beendet, starte ${STAGES[*]}"
fi
if pgrep -u "$USER" -f "$BUSY" >/dev/null; then
	echo "Ein bench.py-Lauf ist aktiv, erst dessen Ende abwarten:" >&2
	pgrep -a -u "$USER" -f "$BUSY" >&2
	exit 1
fi

for s in "${STAGES[@]}"; do
	echo "=== $(date -Is) Start $s: ${STAGE_CMD[$s]}"
	# shellcheck disable=SC2086  # Befehl ist bewusst wortweise gesplittet
	${STAGE_CMD[$s]}
	rc=$?
	echo "=== $(date -Is) Ende $s (exit $rc)"
	if ((rc != 0)); then
		echo "Abbruch nach Fehler in $s" >&2
		exit "$rc"
	fi
done
echo "=== $(date -Is) alle Stufen fertig: ${STAGES[*]}"
exit 0
}
