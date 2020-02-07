""" Create plots for illustrating the scenario mining process

Creation date: 2020 01 02
Author(s): Erwin de Gelder

Modifications:
2020 01 18 Definition of v+ and v- changed. Now not shifted anymore.
2020 02 07 Put v-(k) on the left of the last sample.
"""

import os
import matplotlib.pyplot as plt
from tikzplotlib import save
import numpy as np
import pandas as pd
from activity_detector import ActivityDetector, ActivityDetectorParameters

# General plot parameters
LINEWIDTH = 5
TXT_PARMS = dict(fontsize=20, zorder=1)
FIGURES_FOLDER = os.path.join("..", "..", "20191010 Scenario Mining", "figures")
COLORS = ((1, .2, .2),
          (.2, 1, .2),
          (.2, .2, 1))
np.random.seed(0)

# Parameters for the plot for the longitudinal activities.
SPEEDS = [7.5, 12.5, 2.5]
ACCELERATIONS = [2, -3.5]
JERKS = [3, 5]
CRUISING_TIMES = [2, 4]
TOTAL_TIME = 13
SAMPLE_TIME = 0.01

# Parameters for the plot for the host lane change.
TIMING = [5, 10, 5]
LANEWIDTH = 2.5


def apply_jerk(jerk_vec, time, acceleration, jerk):
    """ Apply the jerk to achieve a certain acceleration. """
    tstart = np.round((time - abs(acceleration / jerk / 2)) / SAMPLE_TIME).astype(np.int)
    tend = np.round((time + abs(acceleration / jerk / 2)) / SAMPLE_TIME).astype(np.int)
    jerk_vec[tstart:tend] = abs(jerk) * np.sign(acceleration)


def speed_profile():
    """ Construct the speed profile for the longitudinal activities. """
    time_vec = np.arange(0, TOTAL_TIME, SAMPLE_TIME)
    jerk_vec = np.zeros_like(time_vec)
    time = 0
    for i, (acceleration, jerk, tcruise) in enumerate(zip(ACCELERATIONS, JERKS, CRUISING_TIMES)):
        time += tcruise
        apply_jerk(jerk_vec, time, acceleration, jerk)
        time += (SPEEDS[i+1] - SPEEDS[i]) / acceleration
        apply_jerk(jerk_vec, time, -acceleration, jerk)
    acceleration = np.cumsum(jerk_vec) * SAMPLE_TIME
    acceleration += np.random.randn(len(jerk_vec))*0.5
    speed = np.cumsum(acceleration) * SAMPLE_TIME + SPEEDS[0]

    # Add few seconds before the start and after the end.
    extra_time = 2
    time_vec = np.concatenate((np.arange(-extra_time, 0, SAMPLE_TIME), time_vec,
                               np.arange(TOTAL_TIME, TOTAL_TIME+extra_time, SAMPLE_TIME)))
    speed = np.concatenate((np.ones(np.round(extra_time/SAMPLE_TIME).astype(np.int))*SPEEDS[0],
                            speed,
                            np.ones(np.round(extra_time/SAMPLE_TIME).astype(np.int))*speed[-1]))
    return time_vec, speed


def lane_change_distances():
    """ Return the lane change distances. """
    time = np.arange(0, np.sum(TIMING), SAMPLE_TIME)
    ypos = np.array(np.zeros_like(time))
    istart = np.round(TIMING[0] / SAMPLE_TIME).astype(np.int)
    iend = np.round(np.sum(TIMING[:2]) / SAMPLE_TIME).astype(np.int)
    ypos[istart:iend] = -(1 - np.cos((time[istart:iend] - TIMING[0])*np.pi/TIMING[1]))*LANEWIDTH/2
    noise = np.random.randn(len(ypos))*0.1
    ypos += np.cumsum(noise)*SAMPLE_TIME
    left = np.mod(LANEWIDTH/2 - ypos, LANEWIDTH)
    right = left - LANEWIDTH

    # Add few seconds before the start and after the end.
    extra_time = 2
    time = np.concatenate((np.arange(-extra_time, 0, SAMPLE_TIME), time,
                           np.arange(time[-1]+SAMPLE_TIME, time[-1]+SAMPLE_TIME+extra_time,
                                     SAMPLE_TIME)))
    left = np.concatenate((np.ones(np.round(extra_time/SAMPLE_TIME).astype(np.int))*left[0],
                           left, np.ones(np.round(extra_time/SAMPLE_TIME).astype(np.int))*left[-1]))
    right = np.concatenate((np.ones(np.round(extra_time/SAMPLE_TIME).astype(np.int))*right[0],
                            right,
                            np.ones(np.round(extra_time/SAMPLE_TIME).astype(np.int))*right[-1]))
    return time, left, right


def save2tikz(name: str):
    """ Save the currently active figure to a tikz file. """
    if not os.path.exists(FIGURES_FOLDER):
        os.mkdir(FIGURES_FOLDER)
    save(os.path.join(FIGURES_FOLDER, '{:s}.tikz'.format(name)),
         figureheight='\\figureheight', figurewidth='\\figurewidth',
         extra_axis_parameters=['axis x line*=bottom', 'axis y line*=left',
                                'every x tick/.style={black}', 'every y tick/.style={black}'])


if __name__ == "__main__":
    # Plot for longitudinal activities
    TIME, SPEED = speed_profile()
    DATA = pd.DataFrame(data=dict(Host_vx=SPEED), index=TIME)
    ACTIVITY_DETECTOR = ActivityDetector(DATA, ActivityDetectorParameters(min_cruising_time=1))
    EVENTS = ACTIVITY_DETECTOR.lon_activities_host()
    plt.subplots(1, 1)
    plt.plot(DATA["Host_vx"], lw=LINEWIDTH, color=COLORS[0])
    plt.plot(DATA["speed_inc_past"], ls='--', lw=LINEWIDTH, color=COLORS[1])  # = v^+
    plt.plot(DATA["speed_dec_past"], ls=':', lw=LINEWIDTH, color=COLORS[2])  # = v^-
    YLIM = [-5, np.max(SPEEDS)+5]
    for event in EVENTS:
        plt.plot([event[0], event[0]], YLIM, 'k-', lw=LINEWIDTH/2)
    EVENTS += [(TOTAL_TIME, "")]
    for j, event in enumerate(EVENTS[:-1]):
        plt.text((max(event[0], 0) + EVENTS[j + 1][0]) / 2, YLIM[1] - 2, event[1].value,
                 HorizontalAlignment="center", **TXT_PARMS)
    plt.xlabel("Time [s]")
    plt.ylabel("Speed [m/s]")
    plt.xlim(0, TOTAL_TIME)
    plt.ylim(YLIM)
    save2tikz("lon_activities")

    # Plot for lateral activities.
    TIME, LEFT, RIGHT = lane_change_distances()
    DATA = pd.DataFrame(data=dict(lines_0_c0=LEFT, lines_0_quality=np.ones_like(LEFT)*3,
                                  lines_1_c0=RIGHT, lines_1_quality=np.ones_like(RIGHT)*3),
                        index=TIME)
    ACTIVITY_DETECTOR = ActivityDetector(DATA,
                                         ActivityDetectorParameters(lateral_speed_lane_change=0.1))
    EVENTS = ACTIVITY_DETECTOR.lat_activities_host()
    plt.subplots(1, 1)
    plt.plot(DATA["lines_0_c0"], lw=LINEWIDTH, color=COLORS[0])
    plt.plot(DATA["line_left_up"], lw=LINEWIDTH, ls='--', color=COLORS[1])
    YLIM = [-1, LANEWIDTH+1.5]
    for event in EVENTS:
        plt.plot([event[0], event[0]], YLIM, 'k-', lw=LINEWIDTH/2)
    for xtext, text in zip([EVENTS[1][0] / 2, (EVENTS[1][0] + EVENTS[2][0]) / 2,
                            (EVENTS[2][0]+np.sum(TIMING))/2],
                           ["following lane", "changing lane\n to right", "following lane"]):
        plt.text(xtext, YLIM[1] - 0.1, text, HorizontalAlignment="center", VerticalAlignment="top",
                 **TXT_PARMS)
    plt.xlabel("Time [s]")
    plt.ylabel("Distance [m]")
    plt.xlim(0, np.sum(TIMING))
    plt.ylim(YLIM)
    save2tikz("ego_lane_change")

    # Plot hypothetical speed to show vmin, vmax, v+ and v-.
    SAMPLE = 13
    HORIZON = 10
    YLIM = [0, 30]
    PLT_PARMS = dict(color=(0, 0, 0), ls='--')
    ARR_PARMS = dict(head_width=1, length_includes_head=True, fc=(1, 1, 1), overhang=1)
    ARR_POS = 0.6
    plt.subplots(1, 1)
    XDATA = np.arange(0, 17)
    XLIM = [min(XDATA), max(XDATA)+0.5]
    YDATA = 16+9*np.sin(XDATA/2) + 2*np.random.randn(len(XDATA))
    plt.plot(XDATA, YDATA, 'o')
    YMIN = np.min(YDATA[SAMPLE-HORIZON:SAMPLE+1])
    YMAX = np.max(YDATA[SAMPLE-HORIZON:SAMPLE+1])
    for xdata in [SAMPLE-HORIZON, SAMPLE]:
        plt.plot([xdata, xdata], YLIM, **PLT_PARMS)
    for ydata in [YMIN, YMAX]:
        plt.plot(XLIM, [ydata, ydata], **PLT_PARMS)
    plt.xticks([SAMPLE-HORIZON, SAMPLE], ["$k-k_h$", "$k$"])
    plt.yticks([np.min(YDATA), np.max(YDATA)], [r"$v_{\mathrm{min}}(k)$", r"$v_{\mathrm{max}}(k)$"])
    plt.plot([SAMPLE-ARR_POS-1, SAMPLE+ARR_POS+1], [YDATA[SAMPLE], YDATA[SAMPLE]], **PLT_PARMS)
    plt.arrow(SAMPLE-ARR_POS, YDATA[SAMPLE], 0, YMAX-YDATA[SAMPLE], **ARR_PARMS)
    plt.arrow(SAMPLE-ARR_POS, YMAX, 0, YDATA[SAMPLE]-YMAX, **ARR_PARMS)
    plt.arrow(SAMPLE+ARR_POS, YDATA[SAMPLE], 0, YMIN-YDATA[SAMPLE], **ARR_PARMS)
    plt.arrow(SAMPLE+ARR_POS, YMIN, 0, YDATA[SAMPLE]-YMIN, **ARR_PARMS)
    plt.text(SAMPLE-ARR_POS, (YDATA[SAMPLE]+YMAX)/2, "$v^-(k)$", horizontalAlignment="right",
             verticalAlignment="center", **TXT_PARMS)
    plt.text(SAMPLE+ARR_POS, (YDATA[SAMPLE]+YMIN)/2, "$v^+(k)$", horizontalAlignment="left",
             verticalAlignment="center", **TXT_PARMS)
    plt.xlim(XLIM)
    plt.ylim(YLIM)
    plt.xlabel("Sample")
    plt.ylabel(r"$v$")
    save2tikz("explain_symbols")
    plt.show()
