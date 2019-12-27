""" Class for reading and adding extra information to ERP2017 data, including various activities.

Creation date: 2019 08 23
Author(s): Erwin de Gelder

Modifications:
2019 08 27 Use Enums instead of strings for activities. Add activities to dataframe.
2019 11 27 Make separate function to get the name of the signal associated with a target.
2019 12 08 Improve lateral activity detection for host. For targets, it does not work yet.
2019 12 09 Move more general functions to a superclass.
2019 12 26 Lateral events for targets improved.
"""

from typing import Callable, List, NamedTuple, Tuple, Union
from enum import Enum, unique
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from data_handler import DataHandler
from options import Options


LineData = NamedTuple("LineData", [("distance", pd.Series), ("difference", pd.Series)])
TargetLines = NamedTuple("LineData", [("left", pd.Series), ("right", pd.Series),
                                      ("left_up", pd.Series), ("left_down", pd.Series),
                                      ("right_up", pd.Series), ("right_down", pd.Series)])
FromGoal = NamedTuple("FromGoal", [("from_y", float), ("goal_y", float)])


@unique
class LongitudinalActivity(Enum):
    """ Possible longitudinal activities. """
    CRUISING = 'c'
    DECELERATING = 'd'
    ACCELERATING = 'a'


@unique
class LateralActivityHost(Enum):
    """ Possible lateral activities of the host vehicle. """
    LANE_FOLLOWING = 'fl'
    LEFT_LANE_CHANGE = 'l'
    RIGHT_LANE_CHANGE = 'r'


@unique
class LateralActivityTarget(Enum):
    """ Possible lateral activities of a target vehicle. """
    LANE_FOLLOWING = 'fl'
    LEFT_CUT_IN = 'li'
    LEFT_CUT_OUT = 'lo'
    RIGHT_CUT_IN = 'ri'
    RIGHT_CUT_OUT = 'ro'


@unique
class LateralStateTarget(Enum):
    """ Possible lateral state of a target. """
    LEFT = 'l'
    RIGHT = 'r'
    SAME = 's'
    UNKNOWN = 'u'
    NOVEHICLE = 'na'


@unique
class LongitudinalStateTarget(Enum):
    """ Possible longitudinal state of a target. """
    FRONT = 'f'
    REAR = 'r'
    NOVEHICLE = 'na'


@unique
class LeadVehicle(Enum):
    """ Indication whether a target is a lead vehicle or not. """
    LEAD = 'y'
    NOLEAD = 'n'
    NOVEHICLE = 'na'


class ActivityDetectorParameters(Options):
    """ Parameters that are used by the ActivityDetector. """
    # Fields of the DataFrame.
    host_lon_vel = 'Host_vx'
    y_left_line = 'lines_0_c0'
    y_right_line = 'lines_1_c0'
    y_left_line_lin = 'lines_0_c1'
    y_left_line_sqr = 'lines_0_c2'
    y_left_line_cub = 'lines_0_c3'
    y_right_line_lin = 'lines_1_c1'
    y_right_line_sqr = 'lines_1_c2'
    y_right_line_cub = 'lines_1_c3'
    left_conf = 'lines_0_quality'
    right_conf = 'lines_1_quality'
    x_target = 'dx'
    y_target = 'dy'
    v_target = 'vx'
    a_target = 'ax'

    # Parameters that alter the activity detection.
    time_speed_difference = 1  # [s]
    min_speed_difference = 0.5 / 3.6  # [m/s]
    min_activity_speed = 0.25 / 3.6  # [m/s]
    diffspeed_start_act = 0.25 / 3.6  # [m/s]
    min_speed_inc = 4 / 3.6  # [m/s]
    min_cruising_time = 4  # [s]
    max_time_activity = 300  # [s] This speeds up the computation hugely
    max_time_host_lane_change = 10  # [s]
    min_line_quality = 3
    lane_change_threshold = 1  # [m]
    lane_change_magic_time = 1  # [s] No idea why this is one or why it is needed (i.e., why not 0?)
    lane_conf_threshold = 0.25
    max_time_lat_target = 10  # [s]
    factor_goal_y_target = 0.25  # ???
    n_targets = 8
    diff_max_valid_time_host = 7  # [s]
    diff_max_valid_time_target = 2  # [s]

    # Parameters that are changed while processing.
    follow_lane_switch = -1


class ActivityDetector(DataHandler):
    """ Class for adding extra information to a dataframe.

    Attributes:
        data: A pandas dataframe containing all the data OR a path to an HDF5.
        parms: Different kinds of parameters, see ActivityDetectorParameters.
    """
    def __init__(self, data: Union[pd.DataFrame, str],
                 parameters: ActivityDetectorParameters = None, frequency: int = None):
        DataHandler.__init__(self, data, frequency=frequency)
        self.parms = ActivityDetectorParameters() if parameters is None else parameters

    def set_activities(self, func: Callable, name: str, i_target: int = None) -> None:
        """ Compute the activities in the dataframe.

        If the activities are already set in the dataframe, these activities
        will be overwritten.
        The function must return a list of events. The list of events must be a
        list of tuples of the form (index, event). Here, index should be an
        index of the dataframe. The event must be an enumeration that returns a
        string once the .value method is used.

        :param func: The function that returns the events.
        :param name: The name of the field in the dataframe.
        :param i_target: If the activities concern a target vehicle, the number
                         of the target vehicle must be given.
        """
        if i_target is None:
            events = func()
        else:
            events = func(i_target)
        indices = [index for index, _ in events]
        activities = [activity.value for _, activity in events]
        dataframe = self.data if i_target is None else self.targets[i_target]
        dataframe[name] = np.nan
        dataframe.loc[indices, name] = activities
        dataframe[name].ffill(inplace=True)

    def set_lon_activities_host(self) -> None:
        """ Compute and add to dataframe the longitudinal activities of host.

        The longitudinal activities of the host vehicle are already set, then
        these values will be overwritten. The activities are written to
        "host_longitudinal_activity".
        """
        self.set_activities(self.lon_activities_host, "host_longitudinal_activity")

    def lon_activities_host(self, plot: bool = False) -> List[Tuple[float, LongitudinalActivity]]:
        """ Compute the longitudinal activities of the host vehicle.

        The activities accelerating, decelerating, and cruising of the host
        vehicle are detected. However, the events preceding the activities are
        returned. Each event is a tuple of the time and the name of the
        following activity. The name can is of type LongitudinalActivity. The
        returned time corresponds to an index of the dataframe.

        :param plot: Whether to plot the events along with the speed.
        :return: A list of events, where each event is a tuple of its time and
                 the name of the following activity.
        """
        # Compute speed increase in next second.
        shift = np.round(self.parms.time_speed_difference * self.frequency).astype(np.int)
        shifted = self.data[self.parms.host_lon_vel].shift(-shift)
        filtered = shifted.rolling(shift+1).min()
        self.set('speed_inc', shifted - filtered)
        self.set('speed_inc_start', self.get('speed_inc').copy())
        self.data.loc[self.data[self.parms.host_lon_vel] != filtered, 'speed_inc_start'] = 0

        # Compute speed decrease in next second.
        shifted = self.data[self.parms.host_lon_vel].shift(-shift)
        filtered = shifted.rolling(shift+1).max()
        self.set('speed_dec', shifted - filtered)
        self.set('speed_dec_start', self.get('speed_dec').copy())
        self.data.loc[self.data[self.parms.host_lon_vel] != filtered, 'speed_dec_start'] = 0

        event = LongitudinalActivity.CRUISING
        all_events = [(self.data.index[0], event)]
        end_event_time = np.inf
        speed_inc = self.get("speed_inc")
        speed_dec = -self.get("speed_dec")
        for row in self.data.itertuples():
            # Potential acceleration signal when in minimum wrt next second, accelerating and not
            # standing still.
            if event != LongitudinalActivity.ACCELERATING and \
                    row.speed_inc_start >= self.parms.min_speed_difference and \
                    getattr(row, self.parms.host_lon_vel) >= self.parms.min_activity_speed:
                i, is_event = self._end_lon_activity(row.Index, speed_inc)
                if is_event:
                    event = LongitudinalActivity.ACCELERATING
                    all_events.append((row.Index, event))
                    end_event_time = i
            elif event != LongitudinalActivity.DECELERATING and \
                    row.speed_dec_start <= -self.parms.min_speed_difference:
                i, is_event = self._end_lon_activity(row.Index, speed_dec)
                if is_event:
                    event = LongitudinalActivity.DECELERATING
                    all_events.append((row.Index, event))
                    end_event_time = i
            elif event != LongitudinalActivity.CRUISING and row.Index >= end_event_time:
                event = LongitudinalActivity.CRUISING
                all_events.append((row.Index, event))

        # Remove small cruise activities.
        events = self._remove_short_cruising(all_events)

        if plot:
            self.plot_lon_activities_host(events)
        return events

    def _end_lon_activity(self, i: float, speed_difference: pd.Series):
        """ Find first index where speed difference is less than significant.

        :param i: Index of the start of the potential longitudinal activity.
        :param speed_difference: The speed difference (up for accelerating,
                                 down for decelerating).
        :return: A tuple (end_time, is_event). If no activity, is_event is
                 False.
        """
        end_i = np.min((i + self.parms.max_time_activity, self.data.index[-1]))
        # If someone can optimize next line... That line is responsible for 75%
        # of the executing time for longitudinal activities...
        end_i = next((j for j, value in speed_difference[i:end_i].iteritems() if
                      value < self.parms.diffspeed_start_act),
                     self.data.index[-1])

        if abs(self.get(self.parms.host_lon_vel, end_i) - self.get(self.parms.host_lon_vel, i)) < \
                self.parms.min_speed_inc:
            return 0, False
        return end_i, True

    def _remove_short_cruising(self, all_events: List[Tuple[float, LongitudinalActivity]]) -> \
            List[Tuple[float, LongitudinalActivity]]:
        """ Remove all cruising events shorter than a threshold.

        The threshold is set by `min_cruising_time`.

        :param all_events: The initial list of events.
        :return: The filtered events.
        """
        events = []
        i = 0
        while i < len(all_events):
            if i == 0 or i == len(all_events) - 1 or \
                    all_events[i][1] in [LongitudinalActivity.ACCELERATING,
                                         LongitudinalActivity.DECELERATING] or \
                    all_events[i + 1][0] - all_events[i][0] >= self.parms.min_cruising_time:
                events.append(all_events[i])
                i += 1
            elif all_events[i - 1][1] == all_events[i + 1][1]:
                i += 2
            else:
                xvel = self.data[self.parms.host_lon_vel].loc[all_events[i][0]:all_events[i + 1][0]]
                if all_events[i + 1][1] == LongitudinalActivity.ACCELERATING:
                    # Note that the [::-1] is needed to get the latest occurence
                    # of the minimum. This, however, does not swap the index, so
                    # it works fine.
                    events.append((xvel[::-1].idxmin(), LongitudinalActivity.ACCELERATING))
                else:
                    events.append((xvel[::-1].idxmax(), LongitudinalActivity.DECELERATING))
                i += 2
        return events

    def plot_lon_activities_host(self, events: List[Tuple[float, LongitudinalActivity]]) -> None:
        """ Plot the longitudinal activities of the host vehicle.

        :param events: A list of events, where each event is a tuple of its time
                       and the name of the following activity.
        """

        plt.plot(self.data[self.parms.host_lon_vel] * 3.6)
        _, ymax = plt.ylim()
        for index, event in events:
            if event == LongitudinalActivity.ACCELERATING:
                color = (0, .5, 0)
            elif event == LongitudinalActivity.DECELERATING:
                color = (0.5, 0, 0)
            else:
                color = (0, 0, 0.5)
            plt.plot([index, index], [0, ymax], color=color)
        plt.ylim((0, ymax))
        plt.xlabel("Time [s]")
        plt.ylabel("Speed [km/h]")
        plt.title("Green=accelerating, red=decelerating, blue=cruising")

    def set_lat_activities_host(self) -> None:
        """ Compute and add to dataframe the lateral activities of the host.

        The lateral activities of the host vehicle are already set, then these
        values will be overwritten. The activities are written to
        "host_lateral_activity".
        """
        self.set_activities(self.lat_activities_host, "host_lateral_activity")

    def lat_activities_host(self) -> List[Tuple[float, LateralActivityHost]]:
        """ Compute the lateral activities of the host vehicle.

        The following events are possible:
        - fl: follow lane
        - l: A left lane change
        - r: A right lane change.
        A list of events is returned. Each event is a tuple with the time of the
        event and the activity that starts at the time of the event.

        :return: A list of events, where each event is a tuple of its time and
                 the name of the following activity.
        """
        self.set('line_center_y', (self.get(self.parms.y_left_line) +
                                   self.get(self.parms.y_right_line)) / 2)
        self.set('line_left_y_conf', self.get(self.parms.y_left_line))
        self.data.loc[self.get(self.parms.left_conf) < self.parms.min_line_quality,
                      'line_left_y_conf'] = np.nan
        self.set('line_right_y_conf', self.get(self.parms.y_right_line))
        self.data.loc[self.get(self.parms.right_conf) < self.parms.min_line_quality,
                      'line_right_y_conf'] = np.nan
        self.set('line_center_y_conf', self.get('line_center_y'))
        self.data.loc[(self.get(self.parms.left_conf) < self.parms.min_line_quality) |
                      (self.get(self.parms.right_conf) < self.parms.min_line_quality),
                      'line_center_y_conf'] = np.nan
        self.set('line_left_y_conf_down', self.get('line_left_y_conf') -
                 self.data['line_left_y_conf'].rolling(window=self.frequency+1).max())
        self.set('line_right_y_conf_down', self.get('line_right_y_conf') -
                 self.data['line_right_y_conf'].rolling(window=self.frequency+1).max())
        self.set('line_left_y_conf_up', self.get('line_left_y_conf') -
                 self.data['line_left_y_conf'].rolling(window=self.frequency+1).min())
        self.set('line_right_y_conf_up', self.get('line_right_y_conf') -
                 self.data['line_right_y_conf'].rolling(window=self.frequency+1).min())

        # Compute the difference between consecutive valid lane line
        # measurements.
        self.set_diff(self.get(self.parms.left_conf) >= self.parms.min_line_quality,
                      self.parms.y_left_line, self.parms.diff_max_valid_time_host)
        self.set_diff(self.get(self.parms.right_conf) >= self.parms.min_line_quality,
                      self.parms.y_right_line, self.parms.diff_max_valid_time_host)

        event = LateralActivityHost.LANE_FOLLOWING
        events = [(self.data.index[0], event)]

        left_y = self.get(self.parms.y_left_line)
        right_y = self.get(self.parms.y_right_line)
        y_down = (-self.get('line_left_y_conf_down'), -self.get('line_right_y_conf_down'))
        y_up = (self.get('line_left_y_conf_up'), self.get('line_right_y_conf_up'))
        for row in self.data.itertuples():
            # Left lane change (out of ego lane).
            if event != LateralActivityHost.LEFT_LANE_CHANGE and self._potential_llc_host(row):
                begin_i, lane_change = self._start_lane_change(row.Index, events[-1], left_y,
                                                               y_down)
                if lane_change:
                    event = LateralActivityHost.LEFT_LANE_CHANGE
                    events.append((begin_i, event))

            # Right lane change (out of ego lane)
            elif event != LateralActivityHost.RIGHT_LANE_CHANGE and self._potential_rlc_host(row):
                begin_i, lane_change = self._start_lane_change(row.Index, events[-1], -right_y,
                                                               y_up)
                if lane_change:
                    event = LateralActivityHost.RIGHT_LANE_CHANGE
                    events.append((begin_i, event))

            # Follow-Lane
            elif event != LateralActivityHost.LANE_FOLLOWING and row.line_center_y_conf != 0:
                if (row.line_right_y_conf_up < self.parms.lane_conf_threshold or
                        row.line_left_y_conf_up < self.parms.lane_conf_threshold) and \
                        (row.line_left_y_conf_down > -self.parms.lane_conf_threshold or
                         row.line_right_y_conf_down > -self.parms.lane_conf_threshold):
                    event = LateralActivityHost.LANE_FOLLOWING
                    events.append((row.Index, event))

        return events

    def _potential_llc_host(self, row: Tuple) -> bool:
        """ Determine if there could be a lane change to the left.

        There should be a large positive difference for the distances to the
        left and right lane lines.

        :param row: Current data sample.
        :return: Whether there could be a left lane change or not. """
        if getattr(row, "{:s}_diff".format(self.parms.y_left_line)) > \
                self.parms.lane_change_threshold and \
                getattr(row, "{:s}_diff".format(self.parms.y_right_line)) > \
                self.parms.lane_change_threshold:
            return True
        return False

    def _potential_rlc_host(self, row: Tuple) -> bool:
        """ Determine if there could be a lane change to the left.

        There should be a large negative difference for the distances to the
        left and right lane lines.

        :param row: Current data sample.
        :return: Whether there could be a left lane change or not. """
        if getattr(row, "{:s}_diff".format(self.parms.y_left_line)) < \
                -self.parms.lane_change_threshold and \
                getattr(row, "{:s}_diff".format(self.parms.y_right_line)) < \
                -self.parms.lane_change_threshold:
            return True
        return False

    def _start_lane_change(self, i: float, event: Tuple[float, LateralActivityHost],
                           lateral_distance: pd.Series, y_dot: Tuple[pd.Series, pd.Series]) \
            -> Tuple[float, bool]:
        """ Compute the start of a potential lane change.

        If there is no lane change found, (0, False) will be returned.
        If a lane change is found, (begin_time, True) will be returned.

        :param i: The index at which the potential lane change is found.
        :param event: The last event (needed for the last event time).
        :param lateral_distance: The lateral distance toward the left side in
                                 case of a left lane change or right side in
                                 case of a right lane change.
        :param y_dot: The "speed" of the lateral_distance toward the lines.
        :return: starting index and whether there is a lane change.
        """
        begin_i = np.max((i - self.parms.max_time_host_lane_change, event[0]))
        begin_i = next((j for j, left, right in zip(y_dot[0][begin_i:i].index[::-1],
                                                    y_dot[0][begin_i:i].values[::-1],
                                                    y_dot[1][begin_i:i].values[::-1]) if
                        left < self.parms.lane_conf_threshold or
                        right < self.parms.lane_conf_threshold), None)
        if begin_i is None:
            return 0, False

        # Is the following really needed? Not sure when the condition is
        # triggered...
        begin_i = lateral_distance[np.max((begin_i - self.parms.lane_change_magic_time,
                                           self.data.index[0])):begin_i].idxmax()
        next_y = lateral_distance.iat[self.data.index.get_loc(begin_i) + 1]
        if abs(lateral_distance[begin_i] - next_y) > self.parms.lane_change_threshold:
            return 0, False

        return begin_i, True

    def set_target_activities(self, i: int = None) -> None:
        """ Set the lateral and longitudinal activities of a target.

        The activities of the target vehicle are already set, then these values
        will be overwritten. The activities are written to
        "Target_i_longitudinal_activity" and "Target_i_lateral_activity".

        :param i: Index of the target. If not given, all targets are processed.
        """
        if i is None:
            for j in range(len(self.targets)):
                self.set_activities(self.lon_activities_target_i, "longitudinal_activity",
                                    i_target=j)
        else:
            self.set_activities(self.lon_activities_target_i, "longitudinal_activity", i_target=i)
        self.set_activities(self.lat_activities_target_i, "lateral_activity", i_target=i)

    def lon_activities_target_i(self, i: int, plot: bool = False) \
            -> List[Tuple[float, LongitudinalActivity]]:
        """ Compute the longitudinal activities of the i-th target vehicle.

        The activities cruising, decelerating, and accelerating are detected.
        To do this, a new ActivityDetector is constructed with the target
        vehicle as "Host" vehicle.
        Automatically, the same thresholds are used as for the host vehicle.

        :param i: Index of the target.
        :param plot: Whether to plot the events along with the speed.
        :return: A list of events, where each event is a tuple of its time and
                 the name of the following activity.
        """
        parameters = self.parms
        parameters.host_lon_vel = self.parms.v_target
        activity_detector = ActivityDetector(self.targets[i], parameters=parameters,
                                             frequency=self.frequency)
        return activity_detector.lon_activities_host(plot=plot)

    def lat_activities_target_i(self, i: int, plot: bool = False) \
            -> List[Tuple[float, LateralActivityTarget]]:
        """ Compute the lateral activities of the i-th target vehicle.

        The following events are possible:
        - fl: follow lane
        - lo: A left lane change out of the lane of the ego vehicle.
        - li: A left lane change into the lane of the ego vehicle.
        - ro: A right lane change out of the lane of the ego vehicle.
        - ri: A right lane change into the lane of the ego vehicle.
        A list of events is returned. Each event is a tuple with the time of the
        event and the activity that starts at the time of the event.

        :param i: Index of the target.
        :param plot: Whether to plot the events along with the line distances.
        :return: A list of events, where each event is a tuple of its time and
                 the name of the following activity.
        """
        target = self.targets[i]
        self._line_info_target(target)
        self.set_diff(np.logical_not(np.isnan(target["line_left"])), "line_left",
                      self.parms.diff_max_valid_time_target, i)
        self.set_diff(np.logical_not(np.isnan(target["line_right"])), "line_right",
                      self.parms.diff_max_valid_time_target, i)

        event = LateralActivityTarget.LANE_FOLLOWING
        events = [(target.index[0], event)]
        self.parms.follow_lane_switch = 0

        # We are going to grab all line data. By doing this once, we speed up the calculation at a
        # small cost of memory usage.
        lines = TargetLines(left=target['line_left_next'],
                            right=target['line_right_next'],
                            left_down=target['line_left_down'],
                            right_down=target['line_right_down'],
                            left_up=target['line_left_up'],
                            right_up=target['line_right_up'])
        for row in target.iloc[1:].itertuples():
            self.parms.follow_lane_switch -= 1
            valid = not np.isnan(row.line_center) and row.line_right < row.line_left

            # Left lane change out of ego lane.
            if valid and event not in [LateralActivityTarget.LEFT_CUT_IN,
                                       LateralActivityTarget.LEFT_CUT_OUT] and \
                    self._potential_left(row.line_left_next, row.line_left_prev):
                lineinfo = LineData(distance=lines.left, difference=lines.left_down)
                self._update_target_lat_event(row, lineinfo, LateralActivityTarget.LEFT_CUT_OUT,
                                              events)

            # Left lane change into ego lane.
            elif valid and event not in [LateralActivityTarget.LEFT_CUT_IN,
                                         LateralActivityTarget.LEFT_CUT_OUT] and \
                    self._potential_left(row.line_right_next, row.line_right_prev):
                lineinfo = LineData(distance=lines.right, difference=lines.right_down)
                self._update_target_lat_event(row, lineinfo, LateralActivityTarget.LEFT_CUT_IN,
                                              events)

            # Right lane change into ego lane.
            elif valid and event not in [LateralActivityTarget.RIGHT_CUT_IN,
                                         LateralActivityTarget.RIGHT_CUT_OUT] and \
                    self._potential_right(row.line_left_next, row.line_left_prev):
                lineinfo = LineData(distance=-lines.left, difference=lines.left_up)
                self._update_target_lat_event(row, lineinfo, LateralActivityTarget.RIGHT_CUT_IN,
                                              events)

            # Right lane change out of ego lane.
            elif valid and event not in [LateralActivityTarget.RIGHT_CUT_IN,
                                         LateralActivityTarget.RIGHT_CUT_OUT] and \
                    self._potential_right(row.line_right_next, row.line_right_prev):
                lineinfo = LineData(distance=-lines.right, difference=lines.right_up)
                self._update_target_lat_event(row, lineinfo, LateralActivityTarget.RIGHT_CUT_OUT,
                                              events)

            elif events[-1][1] != LateralActivityTarget.LANE_FOLLOWING and \
                    self.parms.follow_lane_switch <= 0:
                event = LateralActivityTarget.LANE_FOLLOWING
                events.append((row.Index, event))

        if plot:
            plt.plot(target["line_left"], '.')
            plt.plot(target["line_right"], '.')
            ymin, ymax = plt.ylim()
            for index, event in events:
                if event in [LateralActivityTarget.LEFT_CUT_IN,
                             LateralActivityTarget.RIGHT_CUT_IN]:
                    color = (.5, 0, 0)
                elif event in [LateralActivityTarget.LEFT_CUT_OUT,
                               LateralActivityTarget.RIGHT_CUT_OUT]:
                    color = (0, .5, 0)
                else:
                    color = (0, 0, 0.5)
                plt.plot([index, index], [ymin, ymax], color=color)
            plt.ylim([ymin, ymax])
            plt.title("Blue=follow lane, Green=cut-out, Red=cut-in")

        return events

    def _line_info_target(self, target: pd.DataFrame) -> None:
        """ Compute the lateral offset of the specific target.

        :param target: The dataframe of the target.
        """
        line_left = (self.data.loc[target.index, self.parms.y_left_line] - target["dy"] +
                     self.data.loc[target.index, self.parms.y_left_line_lin] * target["dx"] +
                     self.data.loc[target.index, self.parms.y_left_line_sqr] * target["dx"]**2 +
                     self.data.loc[target.index, self.parms.y_left_line_cub] * target["dx"]**3)
        line_right = (self.data.loc[target.index, self.parms.y_right_line] - target["dy"] +
                      self.data.loc[target.index, self.parms.y_right_line_lin] * target["dx"] +
                      self.data.loc[target.index, self.parms.y_right_line_sqr] * target["dx"]**2 +
                      self.data.loc[target.index, self.parms.y_right_line_cub] * target["dx"]**3)
        line_left[self.get(self.parms.left_conf) < self.parms.min_line_quality] = np.nan
        line_right[self.get(self.parms.right_conf) < self.parms.min_line_quality] = np.nan
        line_center_y = (line_left + line_right) / 2
        target["line_left"] = line_left
        target["line_right"] = line_right
        target["line_center"] = line_center_y
        rollings_options = dict(window=self.frequency, min_periods=self.frequency//3)
        target["line_left_down"] = line_left - line_left.rolling(**rollings_options).max()
        target["line_left_up"] = line_left - line_left.rolling(**rollings_options).min()
        target["line_right_down"] = line_right - line_right.rolling(**rollings_options).max()
        target["line_right_up"] = line_right - line_right.rolling(**rollings_options).min()

    @staticmethod
    def _potential_left(current_y: float, previous_y: float) -> bool:
        """ Determine whether there is a potential left lane change of target.

        If any of the following is true, a False is returned.
        - The current or previous distance to the left lane line is NaN.
        - The current distance toward the left lane line is larger than or
          equal to 0.
        - The previous distance toward the left lane line is smaller than 0.

        :param current_y: The current distance toward the left lane line.
        :param previous_y: The previous distance toward the left lane line.
        :return: A boolean whether there is a potential lane change.
        """
        if np.isnan(current_y) or np.isnan(previous_y):
            return False
        if current_y >= 0:
            return False
        if previous_y < 0:
            return False
        return True

    def _potential_right(self, current_y: float, previous_y: float) -> bool:
        """ Determine whether there is a potential right lane change of host.

        If any of the following is true, a False is returned.
        - The current or previous distance to the right lane line is NaN.
        - The current distance toward the right lane line is larger than or
          equal to 0.
        - The previous distance toward the left lane line is smaller than 0.

        :param current_y: The current distance toward the right lane line.
        :param previous_y: The previous distance toward the right lane line.
        :return: A boolean whether there is a potential lane change.
        """
        return self._potential_left(-current_y, -previous_y)

    def _update_target_lat_event(self, row, lineinfo: LineData, event: LateralActivityTarget,
                                 events: List[Tuple[float, LateralActivityTarget]]):
        begin_j, end_j, lane_change = self._start_end_target(row, lineinfo, events[-1])
        if lane_change:
            if begin_j == events[-1][0]:
                events.pop(-1)
            events.append((begin_j, event))
            self.parms.follow_lane_switch = (end_j - row.Index) * self.frequency

    def _start_end_target(self, row, lineinfo: LineData,
                          event: Tuple[float, LateralActivityTarget]) -> Tuple[float, float, bool]:
        """ Compute the start and end of a potential lane change of a target.

        If the potential lane change is not a lane change, (0, 0, False) will be
        returned.
        There is no type hinting for the argument "row", because it should be
        returned by pandas itertuples(), which returns a new "class". However,
        it should contain the fields "line_left" and "line_right" of target i
        and it should contain the "Index" of the row.

        :param row: A row of the dataframe.
        :param lineinfo: The distance toward the crossing line and its
                         derivative.
        :param event: The last event.
        :return: The starting index, the end index, and a boolean whether there
                 is a lane change.
        """
        fromgoal = self._goal_left_lane_change(row.line_left, row.line_right)
        begin_j, lane_change = self._start_lc_target(row.Index, fromgoal, lineinfo, event)
        if lane_change:
            end_j, lane_change = self._end_lc_target(row.Index, fromgoal, lineinfo.distance)
            return begin_j, end_j, lane_change
        return 0, 0, False

    def _start_lc_target(self, j: float, fromgoal: FromGoal, lineinfo: LineData,
                         event: Tuple[float, LateralActivityTarget]) -> Tuple[float, bool]:
        """ Compute the starting index of a potential lane change.

        :param j: The index at which the potential lane change is found.
        :param fromgoal: Containing the y-positions of the start and goal of the
                         target.
        :param lineinfo: The distance toward the crossing line and its
                         derivative.
        :param event: The last event.
        :return: The starting index and a boolean whether there is a potential
                 lane change.
        """
        begin_j = np.max((j - self.parms.max_time_lat_target, event[0]))
        start_found = False
        for begin_j, distance in zip(lineinfo.distance[begin_j:j].index[::-1],
                                     lineinfo.distance[begin_j:j][::-1]):
            if begin_j != j and distance < fromgoal.goal_y/2:
                # Why is goal_y divided by 2?
                return 0, False
            if distance > fromgoal.from_y:
                if begin_j == self.data.index[0]:
                    start_found = True
                    break
                prev_begin_j = self.data.index[self.data.index.get_loc(begin_j) - 1]
                if abs(distance - lineinfo.distance[prev_begin_j]) < \
                        self.parms.lane_change_threshold:
                    start_found = True
                break
        if start_found:
            if np.any(lineinfo.difference[begin_j:j] == 0):
                begin_j = \
                    lineinfo.difference[begin_j:j][lineinfo.difference[begin_j:j] == 0].index[-1]
            return begin_j, True
        # It might be possible that the index is at the last event. In this case, it is assumed
        # that the lane change is already ongoing.
        if begin_j == event[0]:
            return begin_j, True
        return 0, False

    def _end_lc_target(self, j: int, fromgoal: FromGoal, line_y):
        """ Compute the end index of a potential lane change.

        :param j: The index at which the potential lane change is found.
        :param fromgoal: Containing the y-positions of the start and goal of the
                         target.
        :param line_y: The distance toward the crossing.
        :return: The end index and a boolean whether there is a lane change.
        """
        end_j = np.min((j + self.parms.max_time_lat_target, self.data.index[-1]))
        for end_j, distance in zip(line_y[j:end_j].index, line_y[j:end_j]):
            if distance > 0:
                return 0, False
            if distance < fromgoal.goal_y:
                prev_end_j = self.data.index[self.data.index.get_loc(end_j) - 1]
                if abs(distance - line_y[prev_end_j]) < self.parms.lane_change_threshold:
                    return end_j, True
                break
        return 0, False

    def _goal_left_lane_change(self, left_y: float, right_y: float) -> FromGoal:
        """ Compute the goal and the starting position of a left lane change.

        :param left_y: Distance toward left line.
        :param right_y: Distance toward right line.
        :return: The lateral position from which the lane change start and where
                 it ends.
        """
        from_y = self.parms.factor_goal_y_target * (left_y - right_y)
        goal_y = -from_y
        return FromGoal(from_y=from_y, goal_y=goal_y)

    def set_states_target(self, target: pd.DataFrame) -> None:
        """ Set the longitudinal and lateral state of a target vehicle.

        :param target: The dataframe of the target.
        """
        # Set the longitudinal state.
        target["longitudinal_state"] = LongitudinalStateTarget.REAR.value
        target.loc[target[self.parms.x_target] >= 0, "longitudinal_state"] = \
            LongitudinalStateTarget.FRONT.value

        # Set the lateral state.
        target["lateral_state"] = LateralStateTarget.UNKNOWN.value
        target.loc[target["line_right"] > 0, "lateral_state"] = LateralStateTarget.RIGHT.value
        target.loc[target["line_left"] < 0, "lateral_state"] = LateralStateTarget.LEFT.value
        target.loc[np.logical_and(target["line_right"] <= 0, target["line_left"] >= 0),
                   "lateral_state"] = LateralStateTarget.SAME.value
        target.loc[np.logical_or(self.data.loc[target.index, self.parms.left_conf] <
                                 self.parms.min_line_quality,
                                 self.data.loc[target.index, self.parms.right_conf] <
                                 self.parms.min_line_quality), "lateral_state"] = \
            LateralStateTarget.UNKNOWN.value
        target.loc[target["line_left"] < target["line_right"], "lateral_state"] = \
            LateralStateTarget.UNKNOWN.value

    def set_lead_vehicle(self) -> None:
        """ Determine the lead vehicle and set the tag accordingly. """
        # Compute the distance of the lead vehicle
        min_dx = np.ones(len(self.data)) * np.inf
        samelane = LateralStateTarget.SAME.value
        for i in range(self.parms.n_targets):
            is_candidate = np.logical_and(self.get_t(i, "lateral_state") == samelane,
                                          self.get_t(i, "dx") > 0,
                                          self.get_t(i, "dx").values < min_dx)
            min_dx[is_candidate] = self.get_t(i, "dx")[is_candidate]

        # Set the tag correctly.
        for i in range(self.parms.n_targets):
            signal = self.set_t(i, "lead_vehicle", LeadVehicle.NOLEAD.value)
            self.data.loc[np.logical_and(self.get_t(i, "lateral_state") == samelane,
                                         self.get_t(i, "dx") == min_dx),
                          signal] = LeadVehicle.LEAD.value
            self.data.loc[self.get_t(i, "id") == 0, signal] = LeadVehicle.NOVEHICLE.value
