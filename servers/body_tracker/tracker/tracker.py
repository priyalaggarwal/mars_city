import sys
import argparse
import os
import threading
import time
import json
import PyTango
import pygame
import math
from PyTango.server import Device, DeviceMeta, attribute, command
from PyTango.server import class_property, device_property
from pykinect import nui
from pykinect.nui.structs import TransformSmoothParameters
from pykinect.nui import SkeletonTrackingState, JointId
from urllib import urlopen


class PyTracker(Device):
    __metaclass__ = DeviceMeta

    POLLING = 30

    # the Tracker object, from which get skeletal data
    tracker = None

    def set_tracker(self, tracker):
        self.tracker = tracker

    def acquire_skeleton_lock(self):
        if (self.tracker is None or
                self.tracker.get_skeleton() is None or
                not self.tracker.get_skeleton_lock().acquire(False)):
            return False
        else:
            return True

    def release_skeleton_lock(self):
        self.tracker.get_skeleton_lock().release()

    joints = [
        'skeleton_head',
        'skeleton_neck',
        'skeleton_left_shoulder',
        'skeleton_right_shoulder',
        'skeleton_left_elbow',
        'skeleton_right_elbow',
        'skeleton_left_hand',
        'skeleton_right_hand',
        'skeleton_torso',
        'skeleton_left_hip',
        'skeleton_right_hip',
        'skeleton_left_knee',
        'skeleton_right_knee',
        'skeleton_left_foot',
        'skeleton_right_foot'
    ]

    attr_init_params = dict(
        dtype=('float32',),
        unit='m',
        max_dim_x=3,
        polling_period=POLLING
    )

    for joint in joints:
        # Attribute definition
        exec "%s = attribute(**attr_init_params)" % joint
        if joint == 'skeleton_head':
            continue
        # Read method definition (except for skeleton_head)
        exec "def read_%s(self):\n\treturn self._%s" % (joint, joint)

    def joint_distance(self, joint_1, joint_2):
        dx = joint_1.x - joint_2.x
        dy = joint_1.y - joint_2.y
        dz = joint_1.z - joint_2.z
        return math.sqrt(dx**2 + dy**2 + dz**2)

    def estimate_height(self):
        sk = self.tracker.get_skeleton()

        if sk is None:
            return -1

        done = False

        self.tracker.get_skeleton_lock().acquire()

        upper_body_height = 0
        right_leg = 0
        left_leg = 0
        try:
            upper_body_height += self.joint_distance(sk[JointId.Head],
                                                     sk[JointId.ShoulderCenter])
            upper_body_height += self.joint_distance(sk[JointId.Spine],
                                                     sk[JointId.ShoulderCenter])
            upper_body_height += self.joint_distance(sk[JointId.Spine],
                                                     sk[JointId.HipCenter])

            # hip_center | avg(hip_left, hip_right)
            avg_hip = sk[JointId.HipLeft]
            avg_hip.x = (sk[JointId.HipLeft].x + sk[JointId.HipRight].x) / 2.0
            avg_hip.y = (sk[JointId.HipLeft].y + sk[JointId.HipRight].y) / 2.0
            avg_hip.z = (sk[JointId.HipLeft].z + sk[JointId.HipRight].z) / 2.0
            upper_body_height += self.joint_distance(avg_hip,
                                                     sk[JointId.HipCenter])

            # left leg
            left_leg += self.joint_distance(sk[JointId.HipLeft],
                                            sk[JointId.KneeLeft])
            left_leg += self.joint_distance(sk[JointId.AnkleLeft],
                                            sk[JointId.KneeLeft])
            left_leg += self.joint_distance(sk[JointId.AnkleLeft],
                                            sk[JointId.FootLeft])

            # right leg
            right_leg += self.joint_distance(sk[JointId.HipRight],
                                             sk[JointId.KneeRight])
            right_leg += self.joint_distance(sk[JointId.AnkleRight],
                                             sk[JointId.KneeRight])
            right_leg += self.joint_distance(sk[JointId.AnkleRight],
                                             sk[JointId.FootRight])

            done = True

        finally:
            self.tracker.get_skeleton_lock().release()

        if done:
            return upper_body_height + ((left_leg + right_leg) / 2.0)
        else:
            return -1

    def joint_to_tuple(self, joint):
        return (joint.x, joint.y, joint.z)

    def get_neck_joint_tuple(self, skeleton):
        # TBD how to convert MS ShoulderCenter/Left/Right in OpenNI Neck
        return (skeleton[JointId.ShoulderCenter].x,
                (skeleton[JointId.ShoulderLeft].y * 0.3 +
                 skeleton[JointId.ShoulderRight].y * 0.3 +
                 skeleton[JointId.ShoulderCenter].y * 0.4),
                skeleton[JointId.ShoulderCenter].z)

    def read_skeleton_head(self):
        # sync access to skeleton
        if not self.acquire_skeleton_lock():
            return self._skeleton_head

        try:
            sk = self.tracker.get_skeleton()

            self._skeleton_neck = self.get_neck_joint_tuple(sk)
            self._skeleton_head = self.joint_to_tuple(sk[JointId.Head])
            self._skeleton_left_shoulder = self.joint_to_tuple(sk[JointId.ShoulderLeft])
            self._skeleton_right_shoulder = self.joint_to_tuple(sk[JointId.ShoulderRight])
            self._skeleton_left_elbow = self.joint_to_tuple(sk[JointId.ElbowLeft])
            self._skeleton_right_elbow = self.joint_to_tuple(sk[JointId.ElbowRight])
            self._skeleton_left_hand = self.joint_to_tuple(sk[JointId.HandLeft])
            self._skeleton_right_hand = self.joint_to_tuple(sk[JointId.HandRight])
            self._skeleton_torso = self.joint_to_tuple(sk[JointId.Spine])
            self._skeleton_left_hip = self.joint_to_tuple(sk[JointId.HipLeft])
            self._skeleton_right_hip = self.joint_to_tuple(sk[JointId.HipRight])
            self._skeleton_left_knee = self.joint_to_tuple(sk[JointId.KneeLeft])
            self._skeleton_right_knee = self.joint_to_tuple(sk[JointId.KneeRight])
            self._skeleton_left_foot = self.joint_to_tuple(sk[JointId.FootLeft])
            self._skeleton_right_foot = self.joint_to_tuple(sk[JointId.FootRight])

            # TODO: user step estimation (and add command)
        finally:
            self.release_skeleton_lock()

        return self._skeleton_head

    @command(dtype_out=float)
    def get_height(self):
        return self.estimate_height()

    def init_device(self):
        Device.init_device(self)
        self.info_stream('In Python init_device method')
        self.set_state(PyTango.DevState.ON)

        # Attribute initialization
        for joint in self.joints:
            setattr(self, '_' + joint, (0, 0, 0))


class Tracker:
    KINECTEVENT = pygame.USEREVENT

    SMOOTH_PARAMS_SMOOTHING = 0.7
    SMOOTH_PARAMS_CORRECTION = 0.4
    SMOOTH_PARAMS_PREDICTION = 0.7
    SMOOTH_PARAMS_JITTER_RADIUS = 0.1
    SMOOTH_PARAMS_MAX_DEV_RADIUS = 0.1
    SMOOTH_PARAMS = TransformSmoothParameters(SMOOTH_PARAMS_SMOOTHING,
                                              SMOOTH_PARAMS_CORRECTION,
                                              SMOOTH_PARAMS_PREDICTION,
                                              SMOOTH_PARAMS_JITTER_RADIUS,
                                              SMOOTH_PARAMS_MAX_DEV_RADIUS)

    device_name = None
    kinect = None

    skeleton = None
    skeleton_lock = threading.Lock()

    def update_skeleton(self, new_skeleton):
        self.skeleton_lock.acquire()
        self.skeleton = new_skeleton
        self.skeleton_lock.release()

    def get_skeleton(self):
        return self.skeleton

    def get_skeleton_lock(self):
        return self.skeleton_lock

    def post_frame(self, frame):
        """Get skeleton events from the Kinect device and post them into the PyGame
        event queue."""
        try:
            pygame.event.post(
                pygame.event.Event(self.KINECTEVENT, skeleton_frame=frame)
            )
        except:
            # event queue full
            pass

    def save_skeletal_data(self, skeleton_frame):
        """Save skeletal data got from Kinect"""
        for index, skeleton_info in enumerate(skeleton_frame.SkeletonData):
            if skeleton_info.eTrackingState == SkeletonTrackingState.TRACKED:
                self.update_skeleton(skeleton_info.SkeletonPositions)
                # manage only the first tracked skeleton
                return

    def log_skeletal_data(self, log_file_name):
        # save to json file
        file = open(log_file_name, 'a')
        file.write(self.skeleton_to_json() + '\n')
        file.close()

    def start_tracker(self, log_file_name=None):
        pygame.init()

        if self.kinect is None:
            self.kinect = nui.Runtime()
            self.kinect.skeleton_engine.enabled = True

        self.kinect.skeleton_frame_ready += self.post_frame

        while True:
            event = pygame.event.wait()

            if event.type == pygame.QUIT:
                break
            elif event.type == self.KINECTEVENT:
                self.kinect._nui.NuiTransformSmooth(event.skeleton_frame,
                                                    self.SMOOTH_PARAMS)
                self.save_skeletal_data(event.skeleton_frame)

                if log_file_name is not None and self.skeleton is not None:
                    self.log_skeletal_data(log_file_name)

    def skeleton_to_json(self):
        """Convert skeleton to json"""
        tmp = [None] * JointId.count
        for joint_type, j in enumerate(self.skeleton):
            tmp[joint_type] = {'x': j.x, 'y': j.y, 'z': j.z, 'w': j.w}
        return json.dumps(tmp)

    def json_to_skeleton(self, json_data):
        """Convert json to a skeleton"""
        data = json.loads(json_data)
        tmp = [None] * JointId.count
        for joint_type, j in enumerate(data):
            tmp[joint_type] = nui.Vector(j['x'], j['y'], j['z'], j['w'])
        return tmp

    def start_emulate_tracker(self, sim_file_name):
        """Start a fake tracker, that reads from a file some\
        joints instead of getting them from an actual Kinect device"""
        # Kinect works at 30fps
        polling = 1.0/30.0
        with open(sim_file_name) as f:
            while True:
                line = f.readline()
                if not line:
                    f.seek(0)
                else:
                    self.update_skeleton(self.json_to_skeleton(line))
                    time.sleep(polling)

    def set_tracker_in_device(self):
        util = PyTango.Util.instance()
        device = util.get_device_by_name("c3/mac/" + self.device_name)
        device.set_tracker(self)

    def start_tango(self):
        PyTango.server.run((PyTracker,),
                           post_init_callback=self.set_tracker_in_device,
                           args=['tracker', self.device_name])

    def __init__(self, device_name, kinect=None, log=None, sim=None):
        self.device_name = device_name
        self.kinect = kinect

        if log is None:
            if sim is None:
                # start the tracker thread
                track_thr = threading.Thread(target=self.start_tracker)
            else:
                # read from file skeletal data
                track_thr = threading.Thread(target=self.start_emulate_tracker,
                                             args=[sim])
            track_thr.daemon = True
            track_thr.start()

            # start Tango
            self.start_tango()
        else:
            self.start_tracker(log)


if __name__ == '__main__':
    # argument management
    parser = argparse.ArgumentParser(description='Read skeletal data '
                                     'from the Kinect or logfile, and '
                                     'publish them on Tango bus or save '
                                     'on a JSON file.')

    parser.add_argument('device',
                        choices=['eras-1', 'eras-2',
                                 'eras-3', 'eras-4'],
                        help='the device where this data will be published '
                        '(eras-X)')

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--log", help="log the data on a file",
                       metavar="FILENAME", required=False)
    group.add_argument("--sim", help="read data from a log file",
                       metavar="FILENAME", required=False)

    # parse arguments
    try:
        args = parser.parse_args()
    except:
        pass
    else:
        stop = False
        if args.log is not None and os.path.isfile(args.log):
            s = None
            while s != 'y' and s != 'Y' and s != 'n' and s != 'N':
                s = raw_input('File exists. '
                              'Do you want to overwrite it? (y/n) ')
            if s == 'n' or s == 'N':
                stop = True
            else:
                f = open(args.log, 'w')
                f.truncate()
                f.close()
        if args.sim is not None and not os.path.isfile(args.sim):
            print 'error: File does not exist'
            stop = True

        if not stop:
            Tracker(args.device, None, args.log, args.sim)
