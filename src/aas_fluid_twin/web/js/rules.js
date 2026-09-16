// The rule builder: "keep V201 open while Tank B201 volume is above 1 ml".
//
// The signals, their units and the controllable actuators all come from the AAS
// (SimulationControl/ControlModes), so the builder cannot offer a rule the model would refuse.
// A rule takes its actuator off the schedule entirely, which the schedule grid reflects.
//
// A row is written in the operator's terms — which state to hold, on which side of a
// threshold — and translated into the model's single form (open below `on_below`, close above
// `off_above`, optionally inverted) only when it is sent. The switch-back value is where the
// actuator returns; it is proposed as a 5 % band and may be widened, but not closed: with
// the two equal the actuator toggles at every solver step once the level settles on the
// threshold, and a run of eight such rules ran into the worker's 15-minute cap.

const ACTUATOR_HINTS = {
  V204: "fills B201",
  V205: "fills B202",
  V206: "fills B203",
  V201: "drains B201",
  V202: "drains B202",
  V203: "drains B203",
  V209: "to drain X202",
  P201: "dosing pump",
  P202: "discharge pump",
};

const isPump = (actuator) => actuator.startsWith("P");
const stateWords = (actuator) => (isPump(actuator) ? ["on", "off"] : ["open", "closed"]);

/**
 * The model's form of a row: open below `on_below`, close above `off_above`, or the inverse.
 *
 *   hold OPEN   while BELOW x  -> open below x,  close above y (y >= x)
 *   hold CLOSED while ABOVE x  -> the same rule: open below y, close above x (y <= x)
 *   hold OPEN   while ABOVE x  -> inverted: closed below y, open above x   (y <= x)
 *   hold CLOSED while BELOW x  -> inverted: closed below x, open above y   (y >= x)
 */
//: The hysteresis proposed when the user has not chosen one: 5 % of the threshold, at least
//: one unit of the smallest step the field accepts.
export function proposedBack(row) {
  if (row.threshold === null) return null;
  const band = Math.max(Math.abs(row.threshold) * 0.05, 0.01);
  const back = row.direction === "below" ? row.threshold + band : row.threshold - band;
  return Number(back.toPrecision(4));
}

export function toModelRule(row) {
  if (row.threshold === null || backOnWrongSide(row)) return null;
  const back = row.back ?? proposedBack(row);
  if (back === row.threshold) return null;
  const low = Math.min(row.threshold, back);
  const high = Math.max(row.threshold, back);
  const invert = (row.state === "hold") === (row.direction === "above");
  return { actuator: row.actuator, signal: row.signal, on_below: low, off_above: high, invert };
}

/** A switch-back value on the threshold's own side — or on it — would make the actuator chatter. */
function backOnWrongSide(row) {
  if (row.back === null || row.threshold === null) return false;
  return row.direction === "below" ? row.back <= row.threshold : row.back >= row.threshold;
}

export class RuleBuilder {
  /**
   * @param {HTMLElement} root
   * @param {{onChange?: (rules: object[]) => void}} options
   */
  constructor(root, { onChange } = {}) {
    this.root = root;
    this.onChange = onChange;
    this.signals = [];
    this.actuators = [];
    this.rows = [];
  }

  /** @param {{control_signals: object[], control_actuators: string[]}} config */
  configure(config) {
    this.signals = config.control_signals ?? [];
    this.actuators = config.control_actuators ?? [];
    this.render();
  }

  get controlled() {
    return new Set(this.rows.map((row) => row.actuator));
  }

  /** The rules as the model reads them; a half-written row is not a rule yet. */
  get rules() {
    return this.rows.map(toModelRule).filter(Boolean);
  }

  add() {
    const free = this.actuators.find((a) => !this.controlled.has(a)) ?? this.actuators[0];
    const signal = this.signals[0];
    if (!free || !signal) return;
    this.rows.push({
      actuator: free,
      state: "hold", // "hold" = keep it open/on, "release" = keep it closed/off
      signal: signal.key,
      direction: "below",
      threshold: null,
      back: null,
    });
    this.render();
    this.emit();
  }

  remove(index) {
    this.rows.splice(index, 1);
    this.render();
    this.emit();
  }

  emit() {
    this.onChange?.(this.rules);
  }

  render() {
    const list = document.createElement("div");
    list.className = "rule-list";

    this.rows.forEach((row, index) => {
      const signal = this.signals.find((s) => s.key === row.signal) ?? this.signals[0];
      const unit = signal?.unit ? ` ${signal.unit}` : "";
      const [held, released] = stateWords(row.actuator);
      const el = document.createElement("div");
      el.className = "rule";

      const sentence = document.createElement("div");
      sentence.className = "rule-sentence";

      const actuator = select(
        this.actuators.map((name) => ({
          value: name,
          label: `${name}${ACTUATOR_HINTS[name] ? ` · ${ACTUATOR_HINTS[name]}` : ""}`,
          disabled: name !== row.actuator && this.controlled.has(name),
        })),
        row.actuator,
        (value) => {
          row.actuator = value;
          this.render();
          this.emit();
        }
      );
      actuator.className = "rule-actuator";

      const state = select(
        [
          { value: "hold", label: held },
          { value: "release", label: released },
        ],
        row.state,
        (value) => {
          row.state = value;
          this.render();
          this.emit();
        }
      );

      const source = select(
        this.signals.map((s) => ({ value: s.key, label: s.label })),
        row.signal,
        (value) => {
          row.signal = value;
          this.render();
          this.emit();
        }
      );

      const direction = select(
        [
          { value: "below", label: "below" },
          { value: "above", label: "above" },
        ],
        row.direction,
        (value) => {
          row.direction = value;
          this.render();
          this.emit();
        }
      );

      const threshold = number(row.threshold, "—", (value) => {
        row.threshold = value;
        back.placeholder = value === null ? "—" : String(proposedBack(row));
        this.emit();
        this.validate(el, row);
      });
      const back = number(row.back, row.threshold === null ? "—" : String(proposedBack(row)), (value) => {
        row.back = value;
        this.emit();
        this.validate(el, row);
      });
      back.title =
        "Where the actuator switches back. Empty takes the proposed 5 % band; widen it for " +
        "a calmer plant. It cannot equal the threshold — the actuator would then toggle at " +
        "every solver step once the level settles there.";

      sentence.append(
        text("Keep "),
        actuator,
        text(" "),
        state,
        text(" while "),
        source,
        text(" is "),
        direction,
        text(" "),
        threshold,
        text(unit)
      );
      // The hysteresis clause on its own line: optional, and read after the rule itself.
      const backLine = document.createElement("div");
      backLine.className = "rule-sentence rule-back muted";
      backLine.append(
        text(`switch back ${row.direction === "below" ? "above" : "below"} `),
        back,
        text(`${unit} · proposed 5 % band, widen as you like`)
      );

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn ghost small";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => this.remove(index));

      const error = document.createElement("p");
      error.className = "rule-error";
      error.hidden = true;

      el.append(sentence, remove, backLine, error);
      this.validate(el, row);
      list.append(el);
    });

    if (!this.rows.length) {
      const empty = document.createElement("p");
      empty.className = "muted small";
      empty.textContent = this.signals.length
        ? "No rules: every actuator follows the schedule."
        : "The AAS did not describe any control signals.";
      list.append(empty);
    }

    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn ghost small";
    add.textContent = "Add a rule";
    add.disabled = !this.signals.length || this.rows.length >= this.actuators.length;
    add.addEventListener("click", () => this.add());

    const note = document.createElement("p");
    note.className = "hint";
    note.textContent =
      "An actuator with a rule ignores its schedule row for the whole run — the schedule grid " +
      "shows it struck through. Every other actuator follows the schedule as before.";

    this.root.replaceChildren(list, add, note);
  }

  /** The same checks the runner makes, said early and next to the field. */
  validate(el, row) {
    const error = el.querySelector(".rule-error");
    let message = "";
    if (row.threshold === null) {
      message = "give a threshold";
    } else if (backOnWrongSide(row)) {
      const side = row.direction === "below" ? "above" : "below";
      message = `the switch-back value must lie ${side} the threshold — equal to it, the actuator toggles at every solver step`;
    }
    error.textContent = message;
    error.hidden = !message;
    el.classList.toggle("invalid", Boolean(message));
  }
}

function select(options, current, onChange) {
  const el = document.createElement("select");
  for (const { value, label, disabled } of options) {
    const option = new Option(label, value, false, value === current);
    option.disabled = Boolean(disabled);
    el.append(option);
  }
  el.addEventListener("change", () => onChange(el.value));
  return el;
}

function number(value, placeholder, onInput) {
  const el = document.createElement("input");
  el.type = "number";
  el.step = "any";
  el.className = "rule-threshold";
  el.placeholder = placeholder;
  el.value = value ?? "";
  el.addEventListener("input", () => onInput(el.value === "" ? null : Number(el.value)));
  return el;
}

const text = (value) => document.createTextNode(value);
