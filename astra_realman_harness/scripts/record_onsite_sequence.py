#!/usr/bin/env python3
"""Read-only RGB-D/state recorder for operator teleoperation. No actuator imports.
Commands: phase NAME [intent]; query SUBGOAL; command JSON; score JSON; STOP.
phase/score are collection annotations, never model inputs or physical truth.
"""
import argparse, json, queue, sys, threading, time, uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from io_utils import new_run, write_json, strict_json, read_json
from realman_api2_readonly import SDKReadOnly
from onsite_sequence import RGBDSession, save_observation, video_panel, DRIVER, sha, CAMERAS

PHASES = {'reference', 'calibration_pose', 'approach', 'local_occlusion', 'held_object', 'pre_placement', 'post_release'}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arm', choices=['left','right'], default='left')
    p.add_argument('--task', required=True); p.add_argument('--subgoal')
    p.add_argument('--duration', type=float, default=180)
    p.add_argument('--sample-hz', type=float, default=2)
    p.add_argument('--phase', choices=sorted(PHASES), default='reference')
    p.add_argument('--operator-source', choices=['teleoperation', 'physical_leader_follower', 'pendant', 'stationary_reference'], default='teleoperation')
    p.add_argument('--board-description', type=Path, help='Measured board metadata JSON; never guessed dimensions')
    p.add_argument('--interactive', action='store_true'); p.add_argument('--output', type=Path)
    a = p.parse_args()
    camera_configs = list(CAMERAS)
    if a.arm == "right": camera_configs[0] = ("wrist", "right_wrist", "348522072063")
    if not 0 < a.duration <= 600 or not .2 <= a.sample_hz <= 5: p.error('duration 0..600 s; sample-hz .2..5')
    board = read_json(a.board_description) if a.board_description else None
    if board is not None:
        if not isinstance(board, dict) or not board.get('kind') or not board.get('source'):
            p.error('Board requires kind and measured metadata source')
        if board['kind'] == 'chessboard':
            shape, size = board.get('inner_corners'), board.get('square_mm')
            if not isinstance(shape, list) or len(shape) != 2 or any(type(v) is not int or not 2 <= v <= 50 for v in shape):
                p.error('chessboard inner_corners=[columns,rows], both 2..50')
            if size is not None and (type(size) not in (int, float) or not 0 < size < 1000):
                p.error('square_mm must be measured positive number or null (unknown); never a guessed range')
            board['metric_scale_status'] = board.get('metric_scale_status', 'USER_REPORTED_UNMEASURED') if size is not None else 'UNKNOWN_NOT_MEASURED'
    run = new_run(a.output or ROOT/'logs'/('onsite-sequence-'+time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())+'-'+uuid.uuid4().hex[:8]))
    for name in ('sdk', 'inputs', 'scores'): new_run(run/name)
    write_json(run/'source.json', {'argv': sys.argv, 'python': sys.executable,
        'camera_driver': str(DRIVER), 'camera_driver_sha256': sha(DRIVER), 'cameras': camera_configs, 'arm': a.arm,
        'operator_source': a.operator_source, 'raw_commands_source': 'operator command JSON only; never inferred from feedback',
        'task_verbatim': a.task, 'execution_permitted': False,
        'controller_motion_commands_sent': 0, 'gripper_commands_sent': 0, 'model_calls': 0,
        'board': board or 'NO_BOARD_DESCRIPTION; paired scene/SDK-reported data is not completed hand-eye calibration',
        'read_only_calls': ['rm_get_current_arm_state', 'rm_get_current_work_frame', 'rm_get_current_tool_frame', 'rm_get_rm_plus_state_info'],
        'capture_is_atomic': False, 'exposure_synchronization': 'UNKNOWN'})
    commands = queue.Queue()
    if a.interactive:
        def input_loop():
            for line in sys.stdin: commands.put((time.time(), time.monotonic(), line.strip()))
            commands.put((time.time(), time.monotonic(), 'STOP'))
        threading.Thread(target=input_loop, daemon=True).start()
    phase, subgoal = a.phase, a.subgoal or a.task
    rows, writer, stop, last_obs, event_index = [], None, False, None, 0
    reason = 'DURATION_LIMIT'; started = time.monotonic(); wall_start = time.time()
    print('RECORDER '+str(run), flush=True)
    print('READ ONLY | phase approach/local_occlusion/held_object/pre_placement/post_release | query <subgoal> | command <JSON> | score <JSON> | STOP', flush=True)
    events = (run/'operator_events.jsonl').open('x', encoding='utf-8')
    try:
        import cv2
        if board: write_json(run/'board_description.json', board)
        with RGBDSession(camera_configs) as cameras, SDKReadOnly(run/'sdk') as session:
            write_json(run/'camera_profiles.json', cameras.profiles)
            connection = session.connect(a.arm, {'left':'192.168.1.19','right':'192.168.1.18'}[a.arm], 8080)
            write_json(run/'connection.json', connection)
            if not connection['connected']: raise RuntimeError('ARM_CONNECTION_FAILED:'+a.arm)
            # Start data budget after camera warm-up / connection, not beforehand.
            started = time.monotonic(); wall_start = time.time(); next_tick = started
            print('RECORDING_READY | pipelines remain open | no motion sent', flush=True)
            while time.monotonic()-started < a.duration and not stop:
                while not commands.empty():
                    wall, mono, line = commands.get(); event_index += 1
                    event = {'index': event_index, 'host_wall': wall, 'host_monotonic': mono,
                        'raw_operator_text': line, 'last_observation_id': last_obs,
                        'source': a.operator_source, 'sent_to_hardware': False}
                    head, _, tail = line.partition(' ')
                    if head.upper() == 'STOP': stop = True; reason = 'OPERATOR_STOP'
                    elif head == 'phase':
                        candidate, _, intent = tail.partition(' ')
                        if candidate not in PHASES: event['error'] = 'UNKNOWN_PHASE'
                        else:
                            phase = candidate; event['phase'] = phase
                            event['intent_annotation'] = intent or None
                    elif head == 'query' and tail: subgoal = tail; event['subgoal_for_future_inputs'] = tail
                    elif head in ('command', 'score'):
                        try:
                            payload = strict_json(tail)
                            if not isinstance(payload, dict): raise ValueError('OBJECT_REQUIRED')
                            event['operator_payload'] = payload
                            if head == 'score':
                                write_json(run/'scores'/('%06d.json' % event_index),
                                    {'observation_id': last_obs, 'source': 'OPERATOR_POST_OBSERVATION_LABEL',
                                     'observed_at': wall, 'labels': payload, 'included_in_model_input': False})
                            else: event['command_provenance'] = 'OPERATOR_SUPPLIED; recorder does not transmit'
                        except Exception as exc: event['error'] = str(exc)
                    else: event['error'] = 'UNKNOWN_RECORDER_COMMAND'
                    events.write(json.dumps(event, ensure_ascii=False, allow_nan=False)+'\n'); events.flush()
                    print('MARK '+json.dumps(event, ensure_ascii=False), flush=True)
                if stop: break
                if time.monotonic() < next_tick:
                    time.sleep(min(.05, next_tick-time.monotonic())); continue
                samples = cameras.read()
                state_start = time.monotonic(); state_wall = time.time()
                state = session.snapshot(a.arm)
                grip_start = time.time(); grip_mono = time.monotonic()
                gripper = session.connected[a.arm].rm_get_rm_plus_state_info()
                grip_record = {'function': 'rm_get_rm_plus_state_info', 'raw_return': gripper,
                    'host_wall_interval': [grip_start, time.time()], 'host_monotonic_interval': [grip_mono, time.monotonic()]}
                state['host_monotonic_interval'] = [state_start, time.monotonic()]
                state['host_wall_interval'] = [state_wall, time.time()]
                obs, directory = save_observation(run, len(rows), samples, state, grip_record, a.task, phase, camera_configs=camera_configs, arm=a.arm)
                if board:
                    import numpy as np
                    detections = {}
                    for (selector, _, _), sample in zip(camera_configs, samples):
                        rec = {'observation_id': obs['observation_id'], 'image_sha256':
                            next(r['sha256'] for r in obs['rgb'] if r['camera'] == selector),
                            'world_transform': None, 'hand_eye_transform': None,
                            'board_description_sha256': sha(run/'board_description.json')}
                        if board['kind'] == 'chessboard':
                            gray = cv2.cvtColor(sample['rgb'], cv2.COLOR_RGB2GRAY)
                            found, corners = cv2.findChessboardCorners(gray, tuple(board['inner_corners']),
                                cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK)
                            if found:
                                corners = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1),
                                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, .01))
                            rec.update(status='CORNERS_FOUND' if found else 'CORNERS_NOT_FOUND',
                                corners_px=corners.reshape(-1, 2).tolist() if found else None,
                                detector='existing cv2.findChessboardCorners/cornerSubPix',
                                pose_solve='NOT_ATTEMPTED; fixed board relation/SDK FK frame not yet bound')
                        else:
                            rec.update(status='RAW_BOARD_IMAGES_ONLY',
                                reason='This recorder only has verified installed chessboard detector; no tag package installation')
                        detections[selector] = rec
                    write_json(directory/'board_corners.json', detections)
                last_obs = obs['observation_id']
                query = {'query_id': 'q-'+uuid.uuid4().hex, 'observation_id': last_obs,
                    'kind': 'subgoal', 'subgoal': subgoal, 'source': 'OPERATOR_PRE_NEXT_ACTION',
                    'views': [x[0] for x in camera_configs], 'rois': {}}
                write_json(run/'inputs'/('%06d.json' % len(rows)), {'observation_id': last_obs,
                    'action_query': query, 'budget': {'max_views': 3, 'max_rois': 3},
                    'after_action_scores_included': False})
                panel = video_panel(samples, len(rows), phase, camera_configs)
                if writer is None:
                    writer = cv2.VideoWriter(str(run/'side_evidence.avi'), cv2.VideoWriter_fourcc(*'MJPG'),
                        a.sample_hz, (panel.shape[1], panel.shape[0]))
                    if not writer.isOpened(): raise RuntimeError('VIDEO_WRITER_FAILED')
                writer.write(panel)
                row = {'index': len(rows), 'observation_id': last_obs,
                    'observation_path': str((directory/'observation.json').relative_to(run)),
                    'phase_annotation': phase, 'model_input_path': 'inputs/%06d.json' % len(rows),
                    'raw_command': None, 'raw_command_status': 'NOT_CAPTURED_UNLESS_OPERATOR_EVENT_SUPPLIED',
                    'feedback_source': 'READ_ONLY_API2', 'capture_monotonic': obs['captured_monotonic'],
                    'host_readback_span_ms': obs['host_readback_span_ms'],
                    'robot_error': state['canonical']['system_error'], 'physical_success': None}
                rows.append(row)
                print('FRAME %03d | %s | err=%s | span=%.1f ms (readback)' %
                    (row['index'], phase, row['robot_error']['codes'], row['host_readback_span_ms']), flush=True)
                if state['canonical']['system_error']['has_error']:
                    reason = 'ROBOT_ERROR_OBSERVED'; break
                next_tick = max(next_tick+1/a.sample_hz, time.monotonic())
    except KeyboardInterrupt: reason = 'RECORDER_CTRL_C'
    except Exception as exc: reason = type(exc).__name__+':'+str(exc)
    finally:
        if writer: writer.release()
        events.close()
        write_json(run/'index.json', {'episode_id': run.name, 'observations': rows})
        write_json(run/'summary.json', {'run': str(run), 'stop_reason': reason, 'observations': len(rows),
            'recording_wall_start': wall_start, 'recording_wall_end': time.time(),
            'recording_elapsed_s': time.monotonic()-started, 'video_nominal_fps': a.sample_hz,
            'video_timing': 'sample index replay; exact real timing is in index/observation, not encoded variable FPS',
            'motion_commands_sent': 0, 'gripper_commands_sent': 0, 'model_calls': 0,
            'robot_STOP_semantics': 'Recorder STOP/Ctrl-C stops recording only, does not stop a separate teleoperator'})
        print('SAVED '+str(run), flush=True)
    return 0 if reason in ('DURATION_LIMIT', 'OPERATOR_STOP', 'RECORDER_CTRL_C') else 1

if __name__ == '__main__': raise SystemExit(main())
