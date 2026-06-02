#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI-Agency Balloon Task
======================
Based on Beyer et al. (2017, 2018) marble/balloon task.

Research question:
    Does AI decision support induce diffusion of responsibility by
    reducing subjective sense of agency, similar to social contexts?

Four within-subject conditions (randomized):
    1. nonsocial       — participant alone, no AI
    2. social          — co-player avatar present, no AI
    3. ai_nonsocial    — participant alone, AI hint active
    4. ai_social       — co-player present AND AI hint active

EEG Trigger codes:
    Condition cue onset:  nonsocial=11, social=12, ai_nonsocial=13, ai_social=14
    Balloon start:        21
    Speed-up onset:       22
    AI hint onset:        31
    Participant stops:    41
    Co-player stops:      42
    Balloon pops:         51
    Outcome onset:        61
    Agency rating onset:  71

Requirements:
    PsychoPy >= 2023.1
    balloon.png, pin.png, gpt_logo.png, participant_avatar.jpeg,
    coplayer_avatar.jpeg — all in the same folder as this script
    pyserial for EEG serial port triggers
"""

from psychopy import visual, core, event, gui
import random, os, csv, datetime, serial

# ─────────────────────────────────────────────────────────────────────────────
# EEG trigger
# ─────────────────────────────────────────────────────────────────────────────

# Set the port name for your system:
#   Mac/Linux: "/dev/tty.usbserial-XXXX"  (run 'ls /dev/tty.*' to find yours)
#   Windows:   "COM4"
EEG_SERIAL_PORT = "/dev/tty.usbserial-DN2Q03LO"
EEG_BAUD_RATE   = 115200

port = None   # opened later, only if EEG is enabled in the dialog

def send_trigger(code):
    if port is None:
        return
    port.write(code.to_bytes(1, 'big'))
    core.wait(0.005)
    port.write((0).to_bytes(1, 'big'))
    print(f'trigger sent {code}')

# ─────────────────────────────────────────────────────────────────────────────
# Parameters
# ─────────────────────────────────────────────────────────────────────────────
PARAMS = {
    # Timing
    "condition_display_dur":          2.0,
    "outcome_duration":               2.0,
    "rating_timeout":                 4.0,
    "iti_min":                        1.5,
    "iti_max":                        2.5,
    "outcome_jitter_min":             0.5,
    "outcome_jitter_max":             1.0,

    # Balloon
    "balloon_start_radius":           0.08,
    "balloon_max_radius":             0.28,

    # AI hint
    "ai_hint_soa":                    0.3,   # seconds before speed-up to fire accurate hint
    "ai_accuracy":                    0.70,  # probability of accurate hint

    # Points
    "endowment_per_block":            1000,
    "pop_loss_min":                   80,
    "pop_loss_max":                   99,
    "stop_loss_max":                  30,
    "stop_loss_min":                  1,

    # Co-player
    "coplayer_max_acts_per_block":    6,

    # Task structure
    "trials_per_condition_per_block": 10,   # 10 × 4 = 40 trials/block
    "n_blocks":                       5,
}

# ─────────────────────────────────────────────────────────────────────────────
# Balloon speed profiles
# ─────────────────────────────────────────────────────────────────────────────
# Each profile is (slow_secs, fast_secs, slow_spd).
#   slow_secs  — duration of the slow phase (seconds)
#   fast_secs  — duration of the fast phase (seconds); balloon pops at the end
#   slow_spd   — baseline growth rate (radius/second)
# fast_spd is derived automatically so the balloon always reaches
# balloon_max_radius exactly at slow_secs + fast_secs.

RAW_PROFILES = [
    (4.0, 1.0, 0.030),   # profile 1
    (3.0, 1.8, 0.040),   # profile 2
    (5.0, 2.0, 0.024),   # profile 3
    (4.0, 0.5, 0.030),   # profile 4
    (3.0, 1.0, 0.040),   # profile 5
    (5.0, 0.8, 0.024),   # profile 6
    (6.0, 1.2, 0.020),   # profile 7
    (5.0, 0.5, 0.012),   # profile 8
    (4.5, 0.3, 0.015),   # profile 9
    (5.5, 0.4, 0.020),   # profile 10
]

COND_NONSOCIAL    = "nonsocial"
COND_SOCIAL       = "social"
COND_AI_NONSOCIAL = "ai_nonsocial"
COND_AI_SOCIAL    = "ai_social"

TRIG = {
    "cue_nonsocial":     11,
    "cue_social":        12,
    "cue_ai_nonsocial":  13,
    "cue_ai_social":     14,
    "balloon_start":     21,
    "speed_up":          22,
    "ai_hint":           31,
    "participant_stops": 41,
    "coplayer_stops":    42,
    "balloon_pops":      51,
    "outcome":           61,
    "rating":            71,
}

COND_TRIGGERS = {
    COND_NONSOCIAL:    TRIG["cue_nonsocial"],
    COND_SOCIAL:       TRIG["cue_social"],
    COND_AI_NONSOCIAL: TRIG["cue_ai_nonsocial"],
    COND_AI_SOCIAL:    TRIG["cue_ai_social"],
}

# ─────────────────────────────────────────────────────────────────────────────
# Participant dialog
# ─────────────────────────────────────────────────────────────────────────────
exp_info = {"Participant Name": "", "Co-player Name": "",
            "Participant ID": "", "Session": "1", "EEG": False}
dlg = gui.DlgFromDict(exp_info, title="Balloon Agency Task")
if not dlg.OK:
    core.quit()

participant_name = exp_info["Participant Name"].strip() or "You"
coplayer_name    = exp_info["Co-player Name"].strip() or "Co-player"
participant_id   = exp_info["Participant ID"]
session          = exp_info["Session"]
date_str         = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

if exp_info["EEG"]:
    port = serial.Serial(EEG_SERIAL_PORT, EEG_BAUD_RATE)

# ─────────────────────────────────────────────────────────────────────────────
# Data file
# ─────────────────────────────────────────────────────────────────────────────
os.makedirs("data", exist_ok=True)
data_filename = f"data/sub-{participant_id}_ses-{session}_{date_str}.csv"
fieldnames = [
    "participant", "session", "block", "trial", "condition", "profile",
    "balloon_pop", "coplayer_acted", "reaction_time",
    "ai_hint_shown", "ai_hint_accurate", "ai_hint_balloon_size",
    "points_lost", "agency_rating", "total_points",
]
data_file   = open(data_filename, "w", newline="")
data_writer = csv.DictWriter(data_file, fieldnames=fieldnames)
data_writer.writeheader()

# ─────────────────────────────────────────────────────────────────────────────
# Window
# ─────────────────────────────────────────────────────────────────────────────
win = visual.Window(
    size=(1920, 1080), fullscr=True,
    color="#1a1a1a", units="height", monitor="testMonitor",
)
win.mouseVisible = False

# ─────────────────────────────────────────────────────────────────────────────
# Layout
# ─────────────────────────────────────────────────────────────────────────────
AVATAR_Y    =  0.0    # avatars and balloon all on the horizontal midline
LABEL_DY    = -0.13   # label sits below avatar centre

PX_PART_NS  = -0.65
PX_AI       = -0.45   # AI icon position (same in social and nonsocial)
PX_COPLAYER =  0.65

# ─────────────────────────────────────────────────────────────────────────────
# Stimuli
# ─────────────────────────────────────────────────────────────────────────────

# ── Text ─────────────────────────────────────────────────────────────────────
outcome_text    = visual.TextStim(win, text="", color="red",
                                  height=0.07, bold=True, pos=(0, 0))
rating_question = visual.TextStim(
    win,
    text="How much control did you feel over the outcome?",
    color="white", height=0.038, pos=(0, 0.15))
no_ctrl_lbl        = visual.TextStim(win, text="No control",
                                     color="white", height=0.028,
                                     pos=(-0.44, -0.07))
full_ctrl_lbl      = visual.TextStim(win, text="Complete control",
                                     color="white", height=0.028,
                                     pos=( 0.44, -0.07))
rating_highlight   = visual.Rect(win, width=0.085, height=0.085,
                                 lineColor="#4fc3f7", lineWidth=5,
                                 fillColor=None)
points_display     = visual.TextStim(win, text="", color="white",
                                     height=0.030, pos=(0.65, 0.45))
pop_text           = visual.TextStim(win, text="POP!", color="red",
                                     height=0.12, bold=True, pos=(0, 0))
fixation           = visual.TextStim(win, text="+", color="white",
                                     height=0.05, pos=(0, 0))
message            = visual.TextStim(win, text="", color="white",
                                     height=0.038, wrapWidth=1.6, pos=(0, 0))

rating_scale_labels = []
for i in range(1, 9):
    x = -0.35 + (i - 1) * 0.10
    rating_scale_labels.append(
        visual.TextStim(win, text=str(i), color="white",
                        height=0.04, pos=(x, 0.0))
    )

# ── Avatar images ─────────────────────────────────────────────────────────────
AVATAR_SIZE = (0.16, 0.16)

PART_IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "participant_avatar.jpeg")
COP_IMG  = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "coplayer_avatar.jpeg")

def make_avatar(px, label, image_file):
    img = visual.ImageStim(win, image=image_file,
                           size=AVATAR_SIZE, pos=(px, AVATAR_Y))
    lbl = visual.TextStim(win, text=label, color="white",
                          height=0.028, pos=(px, AVATAR_Y + LABEL_DY))
    return [img, lbl]

av_part     = make_avatar(PX_PART_NS,  participant_name, PART_IMG)
av_coplayer = make_avatar(PX_COPLAYER, coplayer_name,      COP_IMG)

# ── Action indicator boxes ────────────────────────────────────────────────────
ind_part     = visual.Rect(win, width=0.18, height=0.18,
                           lineColor="red", lineWidth=8, fillColor=None,
                           pos=(PX_PART_NS, AVATAR_Y))
ind_coplayer = visual.Rect(win, width=0.18, height=0.18,
                           lineColor="red", lineWidth=8, fillColor=None,
                           pos=(PX_COPLAYER, AVATAR_Y))

# ── Balloon & pin images (centred at x = 0) ───────────────────────────────────
# Balloon: 448 w × 632 h px  → aspect 0.709
# Pin:     172 w × 449 h px  → aspect 0.383
# Heights in screen-height units; widths derived from aspect ratios.
BALLOON_IMG    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "balloon.png")
PIN_IMG        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pin.png")

BALLOON_ASPECT = 443 / 625
PIN_ASPECT     = 179 / 447

# Pin is fixed near the top of the screen.
# Adjust PIN_Y to move it up or down.
PIN_H = 0.1                   # pin height — smaller than before
PIN_W = PIN_H * PIN_ASPECT
PIN_Y = 0.35                  # pin centre in screen-height units

# Pin tip = bottom of pin image = pin centre - half pin height
PIN_TIP_Y = PIN_Y - PIN_H * 0.5

# Balloon max radius is the distance from balloon centre (AVATAR_Y) to pin tip
PARAMS["balloon_max_radius"] = PIN_TIP_Y - AVATAR_Y

# Scale profiles so balloon always reaches max_radius at slow_secs + fast_secs.
# Each entry: (slow_secs, fast_secs, slow_spd, fast_spd)
def scale_profiles():
    """Derive fast_spd so the balloon reaches max_radius at slow_secs + fast_secs."""
    profiles = []
    dist = PARAMS["balloon_max_radius"] - PARAMS["balloon_start_radius"]
    for slow_secs, fast_secs, slow_spd in RAW_PROFILES:
        fast_spd = (dist - slow_secs * slow_spd) / fast_secs
        profiles.append((slow_secs, fast_secs, slow_spd, fast_spd))
    return profiles

BALLOON_PROFILES = scale_profiles()

BALLOON_MIN_H = PARAMS["balloon_start_radius"] * 2
BALLOON_MIN_W = BALLOON_MIN_H * BALLOON_ASPECT

balloon_img = visual.ImageStim(win, image=BALLOON_IMG,
                                size=(BALLOON_MIN_W, BALLOON_MIN_H),
                                pos=(0.0, AVATAR_Y))
pin_img     = visual.ImageStim(win, image=PIN_IMG,
                                size=(PIN_W, PIN_H),
                                pos=(0.0, PIN_Y))

def reset_balloon():
    balloon_img.size = (BALLOON_MIN_W, BALLOON_MIN_H)

# ── AI icon (image-based, matching reference) ─────────────────────────────────
# Place gpt_logo.png in the same folder as this script.
AI_IMAGE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "gpt_logo.png"
)
AI_SIZE = 0.14

def make_ai_icon(px):
    img    = visual.ImageStim(win, image=AI_IMAGE_FILE,
                               size=(AI_SIZE, AI_SIZE), pos=(px, AVATAR_Y))
    border = visual.Rect(win, width=AI_SIZE, height=AI_SIZE,
                          lineColor="red", lineWidth=6, fillColor=None,
                          pos=(px, AVATAR_Y))
    hint   = visual.TextStim(win, text="Stop now!", color="red", bold=True,
                              height=0.028, pos=(px, AVATAR_Y + LABEL_DY))
    return img, border, hint
ai_icon_img, ai_icon_border, ai_icon_hint = make_ai_icon(PX_AI)

def draw_ai(active):
    ai_icon_img.draw()
    if active:
        ai_icon_border.draw()
        ai_icon_hint.draw()

# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def draw_frame(is_social, has_ai, ai_active,
               show_balloon=True, part_ind=False, cop_ind=False):
    """Draw one complete frame: avatars, AI icon, balloon/pin, points."""
    for s in av_part: s.draw()
    if part_ind: ind_part.draw()
    if is_social:
        for s in av_coplayer: s.draw()
        if cop_ind: ind_coplayer.draw()
    if has_ai:
        draw_ai(ai_active)
    if show_balloon:
        pin_img.draw()
        balloon_img.draw()
    points_display.draw()


def show_fixation(dur):
    t = core.Clock()
    while t.getTime() < dur:
        fixation.draw()
        win.flip()
        if "escape" in event.getKeys():
            cleanup_and_quit()


def get_agency_rating():
    """Press a number key 1–8 to confirm rating immediately.
    Screen shown for up to 4 seconds; returns None if no response."""
    current     = None
    clock       = core.Clock()
    rating_sent = False
    event.clearEvents()
    while clock.getTime() < PARAMS["rating_timeout"]:
        rating_question.draw()
        no_ctrl_lbl.draw()
        full_ctrl_lbl.draw()
        for s in rating_scale_labels:
            s.draw()
        if current is not None:
            x = -0.35 + (current - 1) * 0.10
            rating_highlight.pos = (x, 0.0)
            rating_highlight.draw()
        if not rating_sent:
            win.callOnFlip(send_trigger, TRIG["rating"])
            rating_sent = True
        win.flip()
        for k in event.getKeys(keyList=["escape", "1","2","3","4","5","6","7","8"]):
            if k == "escape":
                cleanup_and_quit()
            elif k in "12345678":
                current = int(k)
                # Show highlight for one frame then return
                rating_question.draw()
                no_ctrl_lbl.draw()
                full_ctrl_lbl.draw()
                for s in rating_scale_labels:
                    s.draw()
                rating_highlight.pos = (-0.35 + (current - 1) * 0.10, 0.0)
                rating_highlight.draw()
                win.flip()
                return current
    return None


def calc_stop_loss(radius):
    frac = ((radius - PARAMS["balloon_start_radius"]) /
            (PARAMS["balloon_max_radius"] - PARAMS["balloon_start_radius"]))
    frac = max(0.0, min(1.0, frac))
    return int(PARAMS["stop_loss_max"] -
               frac * (PARAMS["stop_loss_max"] - PARAMS["stop_loss_min"]))


def cleanup_and_quit():
    if port is not None:
        port.close()
    data_file.close()
    win.close()
    core.quit()

# ─────────────────────────────────────────────────────────────────────────────
# Single trial
# ─────────────────────────────────────────────────────────────────────────────

def run_trial(condition, block_num, trial_num, total_points,
              cop_count, part_count, cop_max, profile_idx):

    is_social = condition in (COND_SOCIAL, COND_AI_SOCIAL)
    has_ai    = condition in (COND_AI_NONSOCIAL, COND_AI_SOCIAL)

    reset_balloon()

    # ── 1. Condition cue — EEG trigger on first flip of context display ───
    # ── 2. Context display (2 s, avatars + static balloon, no inflation) ──
    points_display.text = f"Points: {total_points}"
    t0       = core.Clock()
    cue_sent = False
    while t0.getTime() < PARAMS["condition_display_dur"]:
        draw_frame(is_social, has_ai, False, show_balloon=True)
        if not cue_sent:
            win.callOnFlip(send_trigger, COND_TRIGGERS[condition])
            cue_sent = True
        win.flip()
        if "escape" in event.getKeys():
            cleanup_and_quit()

    # ── 3. Balloon inflation ───────────────────────────────────────────────
    event.clearEvents()
    slow_secs, fast_secs, slow_spd, fast_spd = BALLOON_PROFILES[profile_idx]
    total_duration = slow_secs + fast_secs
    aclock         = core.Clock()
    p_stopped      = False
    c_stopped      = False
    popped         = False
    rt             = None
    ai_on          = False
    ai_hint_balloon_size = None
    start_sent     = False
    speed_up_sent  = False

    # Pre-schedule co-player
    if is_social and part_count > cop_count and cop_count < cop_max:
        r_start = PARAMS["balloon_start_radius"]
        r_max   = PARAMS["balloon_max_radius"]
        cop_trigger_radius = random.uniform(
            r_start + 0.50 * (r_max - r_start),
            r_start + 0.97 * (r_max - r_start)
        )
    else:
        cop_trigger_radius = None

    # AI hint timing:
    # Accurate (70%): fires ai_hint_soa seconds before the speed-up
    # Inaccurate (30%): fires at a random time in the first 10–40% of the slow phase
    if has_ai:
        ai_accurate = random.random() < PARAMS["ai_accuracy"]
        if ai_accurate:
            ai_hint_time = max(0.0, slow_secs - PARAMS["ai_hint_soa"])
        else:
            ai_hint_time = slow_secs * random.uniform(0.10, 0.40)
    else:
        ai_accurate  = None
        ai_hint_time = None

    while True:
        elapsed = aclock.getTime()

        # Compute balloon size directly from elapsed time
        if elapsed <= slow_secs:
            balloon_size = PARAMS["balloon_start_radius"] + elapsed * slow_spd
        else:
            balloon_size = (PARAMS["balloon_start_radius"]
                            + slow_secs * slow_spd
                            + (elapsed - slow_secs) * fast_spd)

        # Update balloon image
        h = balloon_size * 2
        balloon_img.size = (h * BALLOON_ASPECT, h)

        # Pop check
        if balloon_size >= PARAMS["balloon_max_radius"] or elapsed >= total_duration:
            popped = True
            break

        # AI hint
        if has_ai and not ai_on and elapsed >= ai_hint_time:
            ai_on = True
            ai_hint_balloon_size = float(balloon_size)
            win.callOnFlip(send_trigger, TRIG["ai_hint"])

        # Speed-up trigger — fires on first flip after slow phase ends
        if not speed_up_sent and elapsed >= slow_secs:
            win.callOnFlip(send_trigger, TRIG["speed_up"])
            speed_up_sent = True

        # Participant keypress first
        keys = event.getKeys(keyList=["space", "escape"])
        if "escape" in keys:
            cleanup_and_quit()
        if "space" in keys and not p_stopped:
            p_stopped = True
            rt        = float(elapsed)
            if is_social:
                part_count += 1
            send_trigger(TRIG["participant_stops"])
            break

        # Co-player
        if (cop_trigger_radius is not None
                and not c_stopped and not p_stopped
                and balloon_size >= cop_trigger_radius):
            c_stopped = True
            cop_count += 1
            send_trigger(TRIG["coplayer_stops"])
            break

        points_display.text = f"Points: {total_points}"
        draw_frame(is_social, has_ai, ai_on)
        if not start_sent:
            win.callOnFlip(send_trigger, TRIG["balloon_start"])
            start_sent = True
        win.flip()

    # ── 4. Post-action freeze with indicator box ───────────────────────────
    gap1     = random.uniform(PARAMS["outcome_jitter_min"],
                              PARAMS["outcome_jitter_max"])
    tg       = core.Clock()
    pop_sent = False
    while tg.getTime() < gap1:
        points_display.text = f"Points: {total_points}"
        if popped:
            draw_frame(is_social, has_ai, False, show_balloon=False)
            pop_text.draw()
            if not pop_sent:
                win.callOnFlip(send_trigger, TRIG["balloon_pops"])
                pop_sent = True
        elif p_stopped:
            draw_frame(is_social, has_ai, False,
                       show_balloon=True, part_ind=True)
        elif c_stopped:
            draw_frame(is_social, has_ai, False,
                       show_balloon=True, cop_ind=True)
        else:
            draw_frame(is_social, has_ai, False)
        win.flip()
        if "escape" in event.getKeys():
            cleanup_and_quit()

    # ── 5. Compute outcome ─────────────────────────────────────────────────
    if c_stopped:
        points_lost        = 0
        outcome_text.text  = f"{coplayer_name} stopped!\n±0 points"
        outcome_text.color = "white"
    elif p_stopped:
        points_lost        = calc_stop_loss(float(balloon_size))
        outcome_text.text  = f"−{points_lost} points"
        outcome_text.color = "red"
    else:
        popped             = True
        points_lost        = random.randint(PARAMS["pop_loss_min"],
                                            PARAMS["pop_loss_max"])
        outcome_text.text  = f"−{points_lost} points"
        outcome_text.color = "red"

    total_points -= points_lost
    points_display.text = f"Points: {total_points}"

    # ── 6. Display outcome (2 s, blank screen) ─────────────────────────────
    outcome_text.pos = (0, 0)
    to               = core.Clock()
    outcome_sent     = False
    while to.getTime() < PARAMS["outcome_duration"]:
        outcome_text.draw()
        if not outcome_sent:
            win.callOnFlip(send_trigger, TRIG["outcome"])
            outcome_sent = True
        win.flip()
        if "escape" in event.getKeys():
            cleanup_and_quit()

    show_fixation(random.uniform(PARAMS["outcome_jitter_min"],
                                 PARAMS["outcome_jitter_max"]))

    # ── 7. Agency rating ───────────────────────────────────────────────────
    agency_rating = get_agency_rating()
    event.clearEvents()   # prevent confirming spacebar leaking into ITI

    show_fixation(random.uniform(PARAMS["iti_min"], PARAMS["iti_max"]))

    # ── 8. Save row ────────────────────────────────────────────────────────
    data_writer.writerow({
        "participant":          participant_id,
        "session":              session,
        "block":                block_num,
        "trial":                trial_num,
        "condition":            condition,
        "profile":              profile_idx + 1,
        "balloon_pop":          int(popped),
        "coplayer_acted":       int(c_stopped),
        "reaction_time":        round(rt, 4) if rt else "NA",
        "ai_hint_shown":        int(ai_on),
        "ai_hint_accurate":     int(ai_accurate) if ai_accurate is not None else "NA",
        "ai_hint_balloon_size": round(ai_hint_balloon_size, 4)
                                if ai_hint_balloon_size else "NA",
        "points_lost":          points_lost,
        "agency_rating":        agency_rating if agency_rating else "NA",
        "total_points":         total_points,
    })
    data_file.flush()
    return total_points, cop_count, part_count

# ─────────────────────────────────────────────────────────────────────────────
# Block runner
# ─────────────────────────────────────────────────────────────────────────────

def run_block(block_num, conditions):
    total   = PARAMS["endowment_per_block"]
    cc      = 0   # co-player acts this block
    pc      = 0   # participant acts on social trials this block
    cop_max = PARAMS["coplayer_max_acts_per_block"]
    random.shuffle(conditions)
    # Assign profiles in random order, cycling through all 10 across trials
    profile_order = list(range(len(BALLOON_PROFILES)))
    random.shuffle(profile_order)
    for n, cond in enumerate(conditions):
        profile_idx = profile_order[n % len(profile_order)]
        total, cc, pc = run_trial(cond, block_num, n + 1, total,
                                  cc, pc, cop_max, profile_idx)
    return total

# ─────────────────────────────────────────────────────────────────────────────
# Instructions
# ─────────────────────────────────────────────────────────────────────────────
def show_instructions():

    def instruction_label(text):
        """Draw a description label at the bottom and a prompt below it."""
        message.text   = text
        message.pos    = (0, -0.38)
        message.height = 0.032
        message.draw()
        visual.TextStim(win, text="Press [SPACE] to continue",
                        color="#aaaaaa", height=0.028, pos=(0, -0.46)).draw()

    def show_page(text):
        """Show a full-screen text page and wait for space."""
        message.text   = text
        message.pos    = (0, 0)
        message.height = 0.038
        event.clearEvents()
        while True:
            message.draw()
            win.flip()
            keys = event.getKeys(["space", "escape"])
            if "escape" in keys: cleanup_and_quit()
            if "space"  in keys: break

    show_page(
        "Welcome to the Balloon Task\n\n"
        "A balloon inflates on screen. Press [SPACE] to stop it\n"
        "before it bursts against the pin at the top.\n\n"
        "The longer you wait, the FEWER points you lose.\n"
        "But if the balloon bursts, you lose the MOST points.\n\n"
        "There are four different types of trials.\n\n"
        "Press [SPACE] to continue."
    )

    # ── Page 2: Individual trial ──────────────────────────────────────────────
    reset_balloon()
    event.clearEvents()
    while True:
        draw_frame(is_social=False, has_ai=False, ai_active=False)
        instruction_label(
            "INDIVIDUAL TRIAL\n"
            "You decide alone when to stop the balloon."
        )
        win.flip()
        keys = event.getKeys(["space", "escape"])
        if "escape" in keys: cleanup_and_quit()
        if "space"  in keys: break

    # ── Page 3: Co-player trial ───────────────────────────────────────────────
    reset_balloon()
    event.clearEvents()
    while True:
        draw_frame(is_social=True, has_ai=False, ai_active=False)
        instruction_label(
            "CO-PLAYER TRIAL\n"
            f"You are playing with {coplayer_name}, who can also stop the balloon.\n"
            f"If {coplayer_name} stops it, you lose 0 points."
        )
        win.flip()
        keys = event.getKeys(["space", "escape"])
        if "escape" in keys: cleanup_and_quit()
        if "space"  in keys: break

    # ── Page 4: AI advisor trial (no signal) ─────────────────────────────────
    reset_balloon()
    event.clearEvents()
    while True:
        draw_frame(is_social=False, has_ai=True, ai_active=False)
        instruction_label(
            "AI ADVISOR TRIAL\n"
            "An AI trained on the task will advise you when to stop. When it signals,\n"
            "a red border appears around the AI icon recommending you stop."
        )
        win.flip()
        keys = event.getKeys(["space", "escape"])
        if "escape" in keys: cleanup_and_quit()
        if "space"  in keys: break

    # ── Page 5: AI advisor trial (signal active) ──────────────────────────────
    reset_balloon()
    event.clearEvents()
    while True:
        draw_frame(is_social=False, has_ai=True, ai_active=True)
        instruction_label(
            "AI ADVISOR TRIAL\n"
            "This signal means the AI recommends stopping.\n"
            "You always decide whether to follow the advice."
        )
        win.flip()
        keys = event.getKeys(["space", "escape"])
        if "escape" in keys: cleanup_and_quit()
        if "space"  in keys: break

    # ── Page 6: Co-player + AI trial ─────────────────────────────────────────
    reset_balloon()
    event.clearEvents()
    while True:
        draw_frame(is_social=True, has_ai=True, ai_active=False)
        instruction_label(
            "CO-PLAYER + AI ADVISOR TRIAL\n"
            f"Both {coplayer_name} and the AI advisor are present.\n"
            "Only you can see the signals from the AI advisor."
        )
        win.flip()
        keys = event.getKeys(["space", "escape"])
        if "escape" in keys: cleanup_and_quit()
        if "space"  in keys: break

    show_page(
        "Control Rating\n\n"
        "After each trial you will be asked:\n\n"
        "'How much control did you feel over the outcome?'\n\n"
        "The outcome being the number of points lost.\n\n"
        "Answer using number keys [1]–[8].\n"
        "1 = No control       8 = Complete control\n\n"
        "Press [SPACE] to continue."
    )

    show_page(
        "Practice\n\n"
        "You will now do a short practice block including\n"
        "all four trial types.\n\n"
        "Ask the experimenter if you have any questions.\n\n"
        "Press [SPACE] to begin practice."
    )


def show_break_screen(block_num, n_blocks, block_points):
    message.text = (
        f"End of Block {block_num} / {n_blocks}\n\n"
        f"Points remaining this block: {block_points}\n\n"
        "Take a short break.\n"
        "Press [SPACE] when you are ready to continue."
    )
    message.pos    = (0, 0)
    message.height = 0.045
    event.clearEvents()
    while True:
        message.draw()
        win.flip()
        keys = event.getKeys(["space", "escape"])
        if "escape" in keys:
            cleanup_and_quit()
        if "space" in keys:
            return


def show_end_screen(total_points):
    earnings_kr = total_points * 0.01
    message.text = (
        f"The task is now complete.\n\n"
        f"Total points saved: {total_points}\n"
        f"You earned {earnings_kr:.2f} kr.\n\n"
        "Thank you for your participation!\n\n"
        "Please let the experimenter know you have finished.\n\n"
        "Press [SPACE] to exit."
    )
    message.pos    = (0, 0)
    message.height = 0.042
    event.clearEvents()
    while True:
        message.draw()
        win.flip()
        if event.getKeys(["space", "escape"]):
            return


# ─────────────────────────────────────────────────────────────────────────────
# Main experiment
# ─────────────────────────────────────────────────────────────────────────────

show_instructions()

# Practice: one of each condition
run_block(block_num=0,
          conditions=[COND_NONSOCIAL, COND_SOCIAL,
                      COND_AI_NONSOCIAL, COND_AI_SOCIAL])

message.text   = (
    "Practice complete!\n\nThe main experiment will now begin.\n\n"
    "Your goal is to lose as few points as possible.\n\n"
    f"Each block = {PARAMS['trials_per_condition_per_block'] * 4} trials.\n\n"
    "Press [SPACE] to start."
)
message.pos    = (0, 0)
message.height = 0.040
event.clearEvents()
while True:
    message.draw()
    win.flip()
    keys = event.getKeys(["space", "escape"])
    if "escape" in keys:
        cleanup_and_quit()
    if "space" in keys:
        break

total_points_saved = 0
for blk in range(1, PARAMS["n_blocks"] + 1):
    conds = (
        [COND_NONSOCIAL]    * PARAMS["trials_per_condition_per_block"] +
        [COND_SOCIAL]       * PARAMS["trials_per_condition_per_block"] +
        [COND_AI_NONSOCIAL] * PARAMS["trials_per_condition_per_block"] +
        [COND_AI_SOCIAL]    * PARAMS["trials_per_condition_per_block"]
    )
    pts = run_block(blk, conds)
    total_points_saved += pts
    if blk < PARAMS["n_blocks"]:
        show_break_screen(blk, PARAMS["n_blocks"], pts)

show_end_screen(total_points_saved)

if port is not None:
    port.close()
data_file.close()
win.close()
core.quit()