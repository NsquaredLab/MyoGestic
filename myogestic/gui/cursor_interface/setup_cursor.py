"""Cursor visualization and control module for MyoGestic.

This module implements the core cursor visualization and control functionality:
- Real-time cursor movement visualization with reference and predicted cursors
- Trajectory-based movement patterns with customizable parameters
- Activation hold points (rest, peak, middle) with configurable thresholds
- Target box visualization for movement guidance
- FPS monitoring for both reference and predicted cursors
- Smooth cursor movement with configurable parameters
- Interactive control via keyboard input

The module provides the following:
- A canvas widget that can be embedded in PySide6 applications
- Signal-based communication for cursor updates and status changes
- Configurable movement patterns and activation parameters
- Real-time performance monitoring
"""

import numpy as np
from vispy import scene
from vispy.scene import visuals
from vispy.io import read_png
from vispy.util.keys import Key
from PySide6.QtCore import QTimer
from vispy.visuals.transforms import STTransform
from PySide6.QtCore import Signal, QObject
import time

from utils.constants import TASKS, DIRECTIONS


class SignalHandler(QObject):
    """Separate QObject to handle signals for VispyWidget."""

    ref_cursor_fps_updated = Signal(float)  # Signal to emit reference cursor FPS
    pred_cursor_fps_updated = Signal(float)  # Signal to emit predicted cursor FPS
    movement_started = Signal()  # Signal for movement start
    movement_stopped = Signal()  # Signal for movement stop


class VispyWidget(scene.SceneCanvas):
    """Vispy canvas widget displaying axes, cursors, task info, and handling key events."""

    def __init__(self, *args, initial_mappings=None, **kwargs):
        scene.SceneCanvas.__init__(self, *args, keys='interactive', bgcolor='black', **kwargs)

        # Initialize movement to cursor direction mapping if argument different from None
        if initial_mappings is None:
            initial_mappings = {}

        self.unfreeze()  # Allow adding attributes

        # Create signal handler
        self.signal_handler = SignalHandler()

        # Add cursor sampling frequency
        self.cursor_sampling_rate: int = 60  # initial value

        # Add FPS tracking attributes
        self._last_ref_cursor_update = time.time()  # used to estimate current FPS of reference cursor
        self._last_pred_cursor_update = time.time()  # used to estimate current FPS of predicted cursor
        self._ref_cursor_display_fps = 0.0
        self._pred_cursor_display_fps = 0.0

        # Initialize cursor direction and trajectory index
        self._current_direction_index = 0  # Index for DIRECTIONS list
        self._current_direction = DIRECTIONS[self._current_direction_index]  # Store current direction string
        self.movement_active = False
        self._movement_mappings = initial_mappings.copy()  # Initialize with provided mappings
        self._trajectories = {}  # Dictionary to hold pre-calculated trajectories
        self._current_trajectory_index = 0  # Index for stepping through trajectory
        self._trajectory_step_size = 1  # Step size for iterating through trajectory points

        # Define task label
        self.task_label = "Inactive"  # Initial task label when cursor is inactive

        # Hold state attributes
        self._rest_hold_duration_ms = 0
        self._rest_hold_point_indices = {}
        self._is_rest_holding = False

        self._peak_hold_threshold = 0.0
        self._peak_hold_duration_ms = 0
        self._peak_hold_point_indices = {}
        self._is_peak_holding = False

        self._middle_hold_threshold = 0.0
        self._middle_hold_duration_ms = 0
        self._middle_hold_stop_condition = "When contracting"  # Default value
        self._middle_hold_contracting_indices = {}
        self._middle_hold_relaxing_indices = {}
        self._is_middle_holding = False
        self._current_index_at_hold_trigger = -1  # Stores the exact index where a hold was triggered

        # Target Box attributes
        self._target_box_visible_flag = False
        self._target_box_lower_pct = 0
        self._target_box_upper_pct = 0

        # Add smoothening factor and last predicted position for cursor smoothing
        self._smoothening_factor = 25.0  # Default smoothening factor
        self.last_predicted_x = 0.0
        self.last_predicted_y = 0.0
        self.pred_is_read = False  # checks whether prediction should be read based on set sampling frequency

        # Add frequency division tracking
        self._pred_freq: int = 60  # Default freq of prediction
        self._freq_div_factor = 1  # Default to display every prediction
        self._prediction_counter = 0  # Counter for received predictions

        # Set up cursor timer for iterating through reference cursor trajectory points
        self.cursor_timer = QTimer()
        self.cursor_timer.timeout.connect(self._on_timer_tick)  # Connect to new timer handler

        self.cursor_timer.setInterval(int(1000 / self.cursor_sampling_rate))  # Set interval based on sampling freq
        self.cursor_timer.start()  # Start timer

        # Get the default view
        self.view = self.central_widget.add_view()
        self.view.camera = scene.PanZoomCamera(aspect=1)
        self.view.camera.set_range(x=(-0.1, 0.1), y=(-1.3, 1.4))  # Set initial zoom/pan

        # Add lab image to canvas
        try:  # try this path if accessed from main script of MyoGestic
            lab_logo = np.flipud(read_png('gui/cursor_interface/assets/n-squared lab Logo.png'))
        except FileNotFoundError:  # try this path if accessed from main_cursor script
            lab_logo = np.flipud(read_png('assets/n-squared lab Logo.png'))

        self.lab_logo = visuals.Image(lab_logo, parent=self.view.scene)
        self.lab_logo.transform = STTransform(scale=(1 / 3000, 1 / 3000), translate=(-0.1, 1.2))  # scale and shift logo
        self.lab_logo.set_gl_state(depth_test=False)

        # Add Uni logo to canvas
        try:
            uni_logo = np.flipud(read_png('gui/cursor_interface/assets/FAU_logo.png'))
        except FileNotFoundError:
            uni_logo = np.flipud(read_png('assets/FAU_logo.png'))

        self.uni_logo = visuals.Image(uni_logo, parent=self.view.scene)
        self.uni_logo.transform = STTransform(
            scale=(1 / 10000, 1 / 10000), translate=(-1.0, 1.15)
        )  # scale and shift logo
        self.uni_logo.set_gl_state(depth_test=False)

        # Add axes to canvas
        self.xaxis = visuals.Axis(
            pos=[[-1.0, 0], [1.0, 0]],
            # tick_direction=(0, -1),
            domain=(-1.0, 1.0),
            text_color=None,
            tick_color=None,
            minor_tick_length=0,
            major_tick_length=0,
            axis_color='white',
            parent=self.view.scene,
        )

        self.xaxis.set_gl_state(depth_test=False)

        self.yaxis = visuals.Axis(
            pos=[[0, -1.0], [0, 1.0]],
            # tick_direction=(-1, 0),
            domain=(-1.0, 1.0),
            text_color=None,
            tick_color=None,
            axis_color='white',
            minor_tick_length=0,
            major_tick_length=0,
            parent=self.view.scene,
        )

        self.yaxis.set_gl_state(depth_test=False)

        # Add a blue predicted cursor at the center
        self.predicted_cursor = visuals.Ellipse(
            center=(0, 0), radius=0.09, color='#6696ff', border_width=0, parent=self.view.scene
        )
        self.predicted_cursor.set_gl_state(depth_test=False)

        # Add a red reference cursor at the center
        self.reference_cursor = visuals.Ellipse(
            center=(0, 0), radius=0.07, color='#ff4e4e', border_width=0, parent=self.view.scene
        )
        self.reference_cursor.set_gl_state(depth_test=False)

        # Add Legend
        legend_font_size = 10
        legend_pos_x = 1.1  # Position in top-left relative to view range
        legend_pos_y_ref = 1.0
        legend_pos_y_pred = 0.9

        self.legend_ref = visuals.Text(
            "Reference",
            parent=self.view.scene,
            color='#ff4e4e',
            pos=(legend_pos_x, legend_pos_y_ref),
            font_size=legend_font_size,
            anchor_x='left',
        )

        self.legend_pred = visuals.Text(
            "Predicted",
            parent=self.view.scene,
            color='#6696ff',
            pos=(legend_pos_x, legend_pos_y_pred),
            font_size=legend_font_size,
            anchor_x='left',
        )

        # Target Box Lines
        line_color = 'yellow'
        line_width = 2.0  # Make it a bit thicker for visibility
        default_pos = np.array([[0, 0], [0, 0]], dtype=np.float32)

        self.target_line_top = scene.visuals.Line(
            pos=default_pos, color=line_color, width=line_width, connect='segments'
        )
        self.view.add(self.target_line_top)

        self.target_line_bottom = scene.visuals.Line(
            pos=default_pos, color=line_color, width=line_width, connect='segments'
        )
        self.view.add(self.target_line_bottom)

        self.target_line_left = scene.visuals.Line(
            pos=default_pos, color=line_color, width=line_width, connect='segments'
        )
        self.view.add(self.target_line_left)

        self.target_line_right = scene.visuals.Line(
            pos=default_pos, color=line_color, width=line_width, connect='segments'
        )
        self.view.add(self.target_line_right)

        self.target_line_top.visible = False
        self.target_line_bottom.visible = False
        self.target_line_left.visible = False
        self.target_line_right.visible = False

        # --- Task Display ---
        task_display_font_size = 12
        task_display_pos = (0, -1.25)  # Bottom center
        self.task_display = visuals.Text(
            "",
            parent=self.view.scene,
            color='white',
            pos=task_display_pos,
            font_size=task_display_font_size,
            anchor_x='center',
        )
        self._update_task_display()  # Set initial text

        self.freeze()  # Prevent adding more attributes

    def get_reference_cursor_position(self):
        """Returns the current (x, y) position of the reference cursor."""
        if hasattr(self, 'reference_cursor') and self.reference_cursor:
            return self.reference_cursor.center  # center is a tuple (x,y)
        return 0.0, 0.0  # Default if not available

    def get_current_direction_string(self):
        """Returns the current active direction string (e.g., "Up", "Rest")."""
        return self._current_direction

    def set_trajectories(self, trajectories):
        """Receives and stores the pre-calculated trajectory arrays."""
        self._trajectories = trajectories.copy()
        self._current_trajectory_index = 0  # Reset index when trajectories change
        self._calculate_activation_point_indices()  # Calculate all hold indices when trajectories update

    def update_movement_mappings(self, mappings):
        """Updates the internal movement mappings and refreshes the display."""
        self._movement_mappings = mappings.copy()
        self._update_task_display()  # Update text when mappings change

    def _update_task_display(self):
        """Updates the text element showing the selected direction and mapped task."""
        selected_direction = DIRECTIONS[self._current_direction_index]
        status = "Active" if self.movement_active else "Paused"  # Removed status

        if selected_direction == "Rest":
            display_text = f"{status}: Middle (Mapped: Rest)"
        else:
            mapped_task = self._movement_mappings.get(selected_direction, "None")
            display_text = f"{status}: {selected_direction} (Mapped: {mapped_task})"

        self.task_display.text = display_text

    def update_activation_parameters(
        self,
        rest_duration_s: float,
        peak_duration_s: float,
        middle_threshold_percent: int,
        middle_duration_s: float,
        middle_stop_condition: str,
        target_box_visible: bool,
        target_box_lower_percent: int,
        target_box_upper_percent: int,
    ):
        """Updates the parameters for all activation holds and target box."""
        # Rest Hold parameters
        self._rest_hold_duration_ms = max(0, int(rest_duration_s * 1000))

        # Peak Hold parameters
        self._peak_hold_threshold = 1.0
        self._peak_hold_duration_ms = max(0, int(peak_duration_s * 1000))

        # Middle Hold parameters
        self._middle_hold_threshold = max(0.0, min(1.0, middle_threshold_percent / 100.0))
        self._middle_hold_duration_ms = max(0, int(middle_duration_s * 1000))
        self._middle_hold_stop_condition = middle_stop_condition

        # Target Box parameters
        self._target_box_visible_flag = target_box_visible
        self._target_box_lower_pct = target_box_lower_percent
        self._target_box_upper_pct = target_box_upper_percent

        # Recalculate hold indices whenever parameters change
        self._calculate_activation_point_indices()
        # Update target box visual as well
        self._update_target_box_visual()

    def _calculate_activation_point_indices(self):
        """Calculates the trajectory indices closest to the thresholds for rest, peak, and middle holds."""
        self._rest_hold_point_indices = {}
        self._peak_hold_point_indices = {}
        self._middle_hold_contracting_indices = {}
        self._middle_hold_relaxing_indices = {}

        for direction, trajectory in self._trajectories.items():
            if trajectory is None or trajectory.shape[0] < 2:  # Need at least 2 points for diff
                continue

            axis_index = 0 if direction in ["Left", "Right"] else 1  # 0 for x, 1 for y
            sign = 1 if direction in ["Up", "Right"] else -1

            # Helper function to find closest index
            def find_closest(target_thresh, data_axis, search_first_half=True):
                """Finds the index of the closest value to target_thresh in data_axis.

                Args:
                    target_thresh: The target threshold value to find.
                    data_axis: The axis data to search in.
                    search_first_half: If True, searches in the first half of the data; otherwise, searches in the
                        second half.

                Returns:
                    The index of the closest value to target_thresh in data_axis.
                """
                if target_thresh == 0 and direction in ["Up", "Right"] and search_first_half:
                    return 0
                elif target_thresh == 0 and direction in ["Down", "Left"] and search_first_half:
                    return 0

                num_points = data_axis.shape[0]
                half_way_index = num_points // 2

                if search_first_half:
                    search_data = data_axis[:half_way_index]
                    offset = 0
                else:  # Search second half
                    search_data = data_axis[half_way_index:]
                    offset = half_way_index

                if search_data.shape[0] == 0:  # Avoid error on empty slice
                    # Fallback to searching whole array if a half is empty (e.g. very short trajectory)
                    diffs = np.abs(data_axis - (sign * target_thresh))
                    return np.argmin(diffs)

                diffs = np.abs(search_data - (sign * target_thresh))
                return np.argmin(diffs) + offset

            try:
                data_axis = trajectory[:, axis_index]
                # Rest Hold (always targets 0%)
                # Find the index closest to 0 on the return path (second half)
                half_way_idx = trajectory.shape[0] // 2
                rest_target_value = 0.0
                rest_diffs = np.abs(data_axis[half_way_idx:] - rest_target_value)
                closest_rest_idx_relative = np.argmin(rest_diffs)
                self._rest_hold_point_indices[direction] = closest_rest_idx_relative + half_way_idx

                # Peak Hold (uses peak threshold)
                self._peak_hold_point_indices[direction] = find_closest(
                    self._peak_hold_threshold, data_axis, search_first_half=True
                )

                # Middle Hold (uses middle threshold and stop condition)
                self._middle_hold_contracting_indices[direction] = find_closest(
                    self._middle_hold_threshold, data_axis, search_first_half=True
                )
                self._middle_hold_relaxing_indices[direction] = find_closest(
                    self._middle_hold_threshold, data_axis, search_first_half=False
                )

            except Exception as e:
                print(f"Warning: Error calculating activation indices for {direction}: {e}")

    def on_key_press(self, event):
        """Handle key press events for direction switching."""
        num_directions = len(DIRECTIONS)
        if event.key == Key('Left'):
            self._current_direction_index = (self._current_direction_index - 1 + num_directions) % num_directions
            self.movement_active = False
            self._is_rest_holding = False  # Reset all hold flags
            self._is_peak_holding = False
            self._is_middle_holding = False
            self._current_index_at_hold_trigger = -1  # Reset hold trigger index
            self.update_reference_cursor(0, 0)
            self._current_direction = DIRECTIONS[self._current_direction_index]  # Update direction string
            self._current_trajectory_index = 0  # Reset index for new direction
            self._update_task_display()
            self._update_target_box_visual()  # Update box on direction change
        elif event.key == Key('Right'):
            self._current_direction_index = (self._current_direction_index + 1) % num_directions
            self.movement_active = False
            self._is_rest_holding = False  # Reset all hold flags
            self._is_peak_holding = False
            self._is_middle_holding = False
            self._current_index_at_hold_trigger = -1  # Reset hold trigger index
            self.update_reference_cursor(0, 0)
            self._current_direction = DIRECTIONS[self._current_direction_index]  # Update direction string
            self._current_trajectory_index = 0  # Reset index for new direction
            self._update_task_display()
            self._update_target_box_visual()  # Update box on direction change
        elif event.key == Key('Space'):
            self.movement_active = not self.movement_active
            self._update_task_display()
            if self.movement_active:
                # Start timer only if direction is not Rest and display freq is valid
                if self._current_direction != "Rest":
                    self._current_trajectory_index = 0  # Reset index on activation
                    self.signal_handler.movement_started.emit()  # Use signal handler
            else:  # Deactivating
                self.signal_handler.movement_stopped.emit()  # Use signal handler
                self._is_rest_holding = False  # Reset all hold flags
                self._is_peak_holding = False
                self._is_middle_holding = False
                self._current_index_at_hold_trigger = -1  # Reset hold trigger index
                # Reset cursor position when paused
                self.update_reference_cursor(0, 0)
                self._update_target_box_visual()  # Update box state (might hide if direction was Rest)

    def update_reference_cursor(self, x, y):
        """Updates the reference cursor position and calculates FPS."""
        self.reference_cursor.center = (x, y)

        # Calculate reference cursor FPS
        current_time = time.time()
        time_diff = current_time - self._last_ref_cursor_update
        if time_diff > 0:  # Avoid division by zero
            self._ref_cursor_display_fps = 1.0 / time_diff
            self.signal_handler.ref_cursor_fps_updated.emit(self._ref_cursor_display_fps)
        self._last_ref_cursor_update = current_time

    def update_predicted_cursor(self, x, y):
        """Updates the predicted cursor position with smoothing and frequency division applied."""
        # Check if it is time to update predicted position
        if time.time() - self._last_pred_cursor_update >= 1 / self._pred_freq:
            # Always calculate smoothed position
            if self._smoothening_factor > 1:
                self.last_predicted_x = (x - self.last_predicted_x) / self._smoothening_factor + self.last_predicted_x
                self.last_predicted_y = (y - self.last_predicted_y) / self._smoothening_factor + self.last_predicted_y
            else:
                # No smoothing, update directly
                self.last_predicted_x = x
                self.last_predicted_y = y

            # Apply prediction frequency division
            self._prediction_counter += 1
            if self._prediction_counter >= self._freq_div_factor:
                # Update cursor display only when counter reaches division factor
                self.predicted_cursor.center = (self.last_predicted_x, self.last_predicted_y)
                # Calculate predicted cursor FPS only when actually displaying
                self._pred_cursor_display_fps = 1.0 / (time.time() - self._last_pred_cursor_update)
                self.signal_handler.pred_cursor_fps_updated.emit(self._pred_cursor_display_fps)

                self._last_pred_cursor_update = time.time()
                self._prediction_counter = 0  # Reset counter after display
                self.pred_is_read = True
        else:
            self.pred_is_read = False

    def _on_timer_tick(self):
        """Handles the timer tick: updates cursor, checking for activation holds."""

        # If currently holding for any reason, do nothing until the hold timer finishes
        if self.movement_active:
            if self._is_rest_holding or self._is_peak_holding or self._is_middle_holding:
                return

            trajectory = self._trajectories.get(self._current_direction)
            if trajectory is None or trajectory.shape[0] == 0:
                return

            candidate_display_index = self._current_trajectory_index

            # Calculate the previous displayed index based on the step size
            prev_displayed_index = (
                candidate_display_index - self._trajectory_step_size + trajectory.shape[0]
            ) % trajectory.shape[0]

            found_hold_type = None
            found_hold_duration = 0
            actual_trigger_index_for_hold = -1

            # Iterate through the trajectory segment to check for holds
            for s_offset in range(self._trajectory_step_size):
                idx_in_segment = (prev_displayed_index + s_offset + 1) % trajectory.shape[0]

                # Check Middle Hold first
                if not found_hold_type and self._middle_hold_duration_ms > 0:
                    middle_contract_idx = self._middle_hold_contracting_indices.get(self._current_direction)
                    middle_relax_idx = self._middle_hold_relaxing_indices.get(self._current_direction)
                    triggered_this_segment = False
                    if self._middle_hold_stop_condition == "When contracting" and middle_contract_idx == idx_in_segment:
                        triggered_this_segment = True
                    elif self._middle_hold_stop_condition == "When relaxing" and middle_relax_idx == idx_in_segment:
                        triggered_this_segment = True
                    elif self._middle_hold_stop_condition == "Both directions" and (
                        middle_contract_idx == idx_in_segment or middle_relax_idx == idx_in_segment
                    ):
                        triggered_this_segment = True

                    if triggered_this_segment:
                        found_hold_type = "Middle"
                        actual_trigger_index_for_hold = idx_in_segment
                        found_hold_duration = self._middle_hold_duration_ms

                # Check Peak Hold (only if middle wasn't triggered yet in this segment scan)
                if not found_hold_type and self._peak_hold_duration_ms > 0:
                    target_peak_index = self._peak_hold_point_indices.get(self._current_direction)
                    if target_peak_index == idx_in_segment:
                        found_hold_type = "Peak"
                        actual_trigger_index_for_hold = idx_in_segment
                        found_hold_duration = self._peak_hold_duration_ms

                # Check Rest Hold (only if middle/peak weren't triggered yet in this segment scan)
                if not found_hold_type and self._rest_hold_duration_ms > 0:
                    target_rest_index = self._rest_hold_point_indices.get(self._current_direction)
                    if target_rest_index == idx_in_segment:
                        found_hold_type = "Rest"
                        actual_trigger_index_for_hold = idx_in_segment
                        found_hold_duration = self._rest_hold_duration_ms

                if (
                    found_hold_type
                ):  # If a hold was found for this idx_in_segment, break from checking further sub-indices.
                    break

            if found_hold_type:
                print(f"{found_hold_type} hold triggered for {found_hold_duration} ms.")
                self._current_index_at_hold_trigger = actual_trigger_index_for_hold  # Store the exact trigger index

                if found_hold_type == "Rest":
                    self._is_rest_holding = True
                elif found_hold_type == "Peak":
                    self._is_peak_holding = True
                elif found_hold_type == "Middle":
                    self._is_middle_holding = True

                x_pos_hold, y_pos_hold = trajectory[actual_trigger_index_for_hold]
                self.update_reference_cursor(x_pos_hold, y_pos_hold)

                if found_hold_type == "Rest":
                    QTimer.singleShot(found_hold_duration, self._resume_rest_hold)
                elif found_hold_type == "Peak":
                    QTimer.singleShot(found_hold_duration, self._resume_peak_hold)
                elif found_hold_type == "Middle":
                    QTimer.singleShot(found_hold_duration, self._resume_middle_hold)
                return

            # --- Normal Movement (No hold triggered in the entire segment) ---
            # Display cursor at the candidate_display_index (which is current _current_trajectory_index)
            x_pos, y_pos = trajectory[candidate_display_index]
            self.update_reference_cursor(x_pos, y_pos)

            # Increment the trajectory index for the next step
            self._current_trajectory_index = (candidate_display_index + self._trajectory_step_size) % trajectory.shape[
                0
            ]

    def _resume_movement_base(self, hold_type: str):
        """Base logic for resuming movement after any hold."""
        print(f"Resuming movement after {hold_type} hold from index {self._current_index_at_hold_trigger}.")

        trajectory = self._trajectories.get(self._current_direction)
        if trajectory is not None and trajectory.shape[0] > 0:
            # Increment index from the actual hold point for the next step
            base_idx_for_resume = self._current_index_at_hold_trigger
            self._current_trajectory_index = (base_idx_for_resume + self._trajectory_step_size) % trajectory.shape[0]
        else:
            self._current_trajectory_index = 0

        self._current_index_at_hold_trigger = -1  # Reset after use

    def _resume_rest_hold(self):
        """Called by the rest hold timer to resume movement."""
        self._is_rest_holding = False
        self._resume_movement_base("Rest")

    def _resume_peak_hold(self):
        """Called by the peak hold timer to resume movement."""
        self._is_peak_holding = False
        self._resume_movement_base("Peak")

    def _resume_middle_hold(self):
        """Called by the middle hold timer to resume movement."""
        self._is_middle_holding = False
        self._resume_movement_base("Middle")

    def _update_target_box_visual(self):
        """Updates the position, size, and visibility of the target box visual (now 4 lines)."""
        if (
            not self._target_box_visible_flag
            or self._current_direction == "Rest"
            or self._trajectories.get(self._current_direction) is None
        ):
            self.target_line_top.visible = False
            self.target_line_bottom.visible = False
            self.target_line_left.visible = False
            self.target_line_right.visible = False
            return

        # Middle activation level (0.0 to 1.0)
        middle_ref_abs = self._middle_hold_threshold

        # Fractional extension amounts from UI percentages
        extend_outward_abs = self._target_box_upper_pct / 100.0
        extend_inward_abs = self._target_box_lower_pct / 100.0

        # Calculate the two primary axis edges based on the middle reference
        # Edge 1: Extending inwards from middle_ref_abs towards 0
        p_axis_1 = middle_ref_abs - extend_inward_abs
        # Edge 2: Extending outwards from middle_ref_abs towards 1.0 (or -1.0 for negative directions)
        p_axis_2 = middle_ref_abs + extend_outward_abs

        # Define the extent of the box perpendicular to the movement direction
        off_axis_half_width = 0.15  # This defines how "wide" the target lines are

        if self._current_direction == "Up":
            y1, y2 = p_axis_1, p_axis_2
            x_left, x_right = -off_axis_half_width, off_axis_half_width
            self.target_line_bottom.set_data(pos=np.array([[x_left, y1], [x_right, y1]], dtype=np.float32))
            self.target_line_top.set_data(pos=np.array([[x_left, y2], [x_right, y2]], dtype=np.float32))
            self.target_line_left.set_data(pos=np.array([[x_left, y1], [x_left, y2]], dtype=np.float32))
            self.target_line_right.set_data(pos=np.array([[x_right, y1], [x_right, y2]], dtype=np.float32))
        elif self._current_direction == "Down":
            y1, y2 = -p_axis_2, -p_axis_1  # Note: signs and order for negative direction
            x_left, x_right = -off_axis_half_width, off_axis_half_width
            self.target_line_bottom.set_data(pos=np.array([[x_left, y1], [x_right, y1]], dtype=np.float32))  # Bottom
            self.target_line_top.set_data(pos=np.array([[x_left, y2], [x_right, y2]], dtype=np.float32))  # Top
            self.target_line_left.set_data(pos=np.array([[x_left, y1], [x_left, y2]], dtype=np.float32))
            self.target_line_right.set_data(pos=np.array([[x_right, y1], [x_right, y2]], dtype=np.float32))
        elif self._current_direction == "Right":
            x1, x2 = p_axis_1, p_axis_2
            y_bottom, y_top = -off_axis_half_width, off_axis_half_width
            self.target_line_left.set_data(pos=np.array([[x1, y_bottom], [x1, y_top]], dtype=np.float32))  # Left
            self.target_line_right.set_data(pos=np.array([[x2, y_bottom], [x2, y_top]], dtype=np.float32))  # Right
            self.target_line_bottom.set_data(pos=np.array([[x1, y_bottom], [x2, y_bottom]], dtype=np.float32))  # Bottom
            self.target_line_top.set_data(pos=np.array([[x1, y_top], [x2, y_top]], dtype=np.float32))  # Top
        elif self._current_direction == "Left":
            x1, x2 = -p_axis_2, -p_axis_1  # Note: signs and order
            y_bottom, y_top = -off_axis_half_width, off_axis_half_width
            self.target_line_left.set_data(pos=np.array([[x1, y_bottom], [x1, y_top]], dtype=np.float32))
            self.target_line_right.set_data(pos=np.array([[x2, y_bottom], [x2, y_top]], dtype=np.float32))
            self.target_line_bottom.set_data(pos=np.array([[x1, y_bottom], [x2, y_bottom]], dtype=np.float32))
            self.target_line_top.set_data(pos=np.array([[x1, y_top], [x2, y_top]], dtype=np.float32))
        else:  # Should not happen if already checked for "Rest", but as a fallback
            self.target_line_top.visible = False
            self.target_line_bottom.visible = False
            self.target_line_left.visible = False
            self.target_line_right.visible = False
            return

        self.target_line_top.visible = True
        self.target_line_bottom.visible = True
        self.target_line_left.visible = True
        self.target_line_right.visible = True

    def update_smoothening_factor(self, factor: int):
        """Updates the smoothening factor for predicted cursor movement."""
        self._smoothening_factor = max(1, factor)  # Ensure factor is at least 1

    def update_freq_div_factor(self, factor: int):
        """Updates the frequency division factor for predicted cursor display."""
        self._freq_div_factor = max(1, factor)  # Ensure factor is at least 1
        self._prediction_counter = 0  # Reset counter when factor changes

    def update_pred_freq(self, pred_freq: int):
        """Updates the frequency for predicted cursor display and streaming."""
        self._pred_freq = pred_freq
