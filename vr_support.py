"""OpenXR setup and generic select input for the Main Hub."""

import ctypes

import xr
from panda3d.core import CS_default, CS_yup_right, LMatrix4, LPoint3, LQuaternion
from p3dopenxr import p3dopenxr as p3d_openxr


class HubActionSet:
    """OpenXR pose tracking plus the standard simple-controller select action."""

    def __init__(self, session, app_space, name, localized_name, priority=0):
        self.session = session
        self.app_space = app_space
        self.coord_mat = LMatrix4.convert_mat(CS_yup_right, CS_default)
        self.pose_links = {}
        instance = session.system.instance
        self.handle = xr.create_action_set(
            instance.handle,
            xr.ActionSetCreateInfo(
                action_set_name=name,
                localized_action_set_name=localized_name,
                priority=priority,
            ),
        )

        self.hands_path_string = ["/user/hand/left", "/user/hand/right"]
        self.hands_path = [
            xr.string_to_path(instance.handle, path)
            for path in self.hands_path_string
        ]
        self.hand_pose_action = xr.create_action(
            action_set=self.handle,
            create_info=xr.ActionCreateInfo(
                action_type=xr.ActionType.POSE_INPUT,
                action_name="hand_pose",
                localized_action_name="Hand Pose",
                count_subaction_paths=len(self.hands_path),
                subaction_paths=self.hands_path,
            ),
        )
        self.select_action = xr.create_action(
            action_set=self.handle,
            create_info=xr.ActionCreateInfo(
                action_type=xr.ActionType.BOOLEAN_INPUT,
                action_name="select",
                localized_action_name="Select",
                count_subaction_paths=len(self.hands_path),
                subaction_paths=self.hands_path,
            ),
        )

        pose_paths = [
            xr.string_to_path(instance.handle, f"{hand}/input/grip/pose")
            for hand in self.hands_path_string
        ]
        select_paths = [
            xr.string_to_path(instance.handle, f"{hand}/input/select/click")
            for hand in self.hands_path_string
        ]
        simple_controller = xr.string_to_path(
            instance.handle, "/interaction_profiles/khr/simple_controller"
        )
        xr.suggest_interaction_profile_bindings(
            instance=instance.handle,
            suggested_bindings=xr.InteractionProfileSuggestedBinding(
                interaction_profile=simple_controller,
                suggested_bindings=[
                    xr.ActionSuggestedBinding(self.hand_pose_action, pose_paths[0]),
                    xr.ActionSuggestedBinding(self.hand_pose_action, pose_paths[1]),
                    xr.ActionSuggestedBinding(self.select_action, select_paths[0]),
                    xr.ActionSuggestedBinding(self.select_action, select_paths[1]),
                ],
            ),
        )

        self.hands_space = [
            xr.create_action_space(
                session=session.handle,
                create_info=xr.ActionSpaceCreateInfo(
                    action=self.hand_pose_action,
                    subaction_path=hand_path,
                ),
            )
            for hand_path in self.hands_path
        ]
        self.select_just_pressed = {"left": False, "right": False}

    def link_pose(self, path, nodepath):
        self.pose_links[path] = nodepath

    def attach(self):
        xr.attach_session_action_sets(
            session=self.session.handle,
            attach_info=xr.SessionActionSetsAttachInfo(
                count_action_sets=1,
                action_sets=ctypes.pointer(self.handle),
            ),
        )

    def poll_actions(self):
        if not self.session.session_active():
            return
        active_action_set = xr.ActiveActionSet(self.handle, xr.NULL_PATH)
        xr.sync_actions(
            self.session.handle,
            xr.ActionsSyncInfo(
                count_active_action_sets=1,
                active_action_sets=ctypes.pointer(active_action_set),
            ),
        )

        for index, (hand_name, hand_path, hand_space) in enumerate(
            zip(("left", "right"), self.hands_path, self.hands_space)
        ):
            pose_state = xr.get_action_state_pose(
                session=self.session.handle,
                get_info=xr.ActionStateGetInfo(
                    action=self.hand_pose_action,
                    subaction_path=hand_path,
                ),
            )
            nodepath = self.pose_links[self.hands_path_string[index]]
            if pose_state.is_active:
                location = xr.locate_space(
                    space=hand_space,
                    base_space=self.app_space.handle,
                    time=self.session.frame_state.predicted_display_time,
                )
                flags = location.location_flags
                valid = (
                    flags & xr.SPACE_LOCATION_POSITION_VALID_BIT
                    and flags & xr.SPACE_LOCATION_ORIENTATION_VALID_BIT
                )
                if valid:
                    nodepath.unstash()
                    nodepath.set_pos(
                        self.coord_mat.xform_point(LPoint3(*location.pose.position))
                    )
                    quat = location.pose.orientation
                    nodepath.set_quat(LQuaternion(quat.w, quat.x, -quat.z, quat.y))
                else:
                    nodepath.stash()
            else:
                nodepath.stash()

            select_state = xr.get_action_state_boolean(
                session=self.session.handle,
                get_info=xr.ActionStateGetInfo(
                    action=self.select_action,
                    subaction_path=hand_path,
                ),
            )
            self.select_just_pressed[hand_name] = bool(
                select_state.is_active
                and select_state.current_state
                and select_state.changed_since_last_sync
            )

    def destroy(self):
        if self.handle is not None:
            xr.destroy_action_set(self.handle)
            self.handle = None


def initialize_openxr(base):
    """Start OpenXR using the shared pose and select action set."""
    p3d_openxr.ActionSet = HubActionSet
    xr_app = p3d_openxr.P3DOpenXR(base=base)
    xr_app.init()
    return xr_app
