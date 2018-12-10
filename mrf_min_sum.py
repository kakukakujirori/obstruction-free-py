import numpy as np
import cv2
from scipy import signal

def ncc(patch1, patch2):
    return (patch1 * patch2).sum() / np.sqrt((patch1 * patch1).sum() * (patch2 * patch2).sum())

def get_patch_pixel_diff(I1, I2, edge_points1, edge_points2, point_id1, motion_x, motion_y, patch_size):
    point1 = edge_points1[point_id1]
    patch1 = I1[point1[0] - patch_size//2:point1[0] + patch_size//2 + 1, point1[1] - patch_size//2:point1[1] + patch_size//2 + 1]
    point2 = [point1[0] - motion_x, point1[1] - motion_y]
    patch2 = I2[point2[0]-patch_size//2:point2[0] + patch_size//2 + 1, point1[1] - patch_size//2:point1[1] + patch_size//2 + 1]
    coeff = ncc(patch1, patch2)
    return 1. - coeff

def get_cost_by_motion(I1, I2, edge_points1, edge_points2, point_id1, max_motion_x, max_motion_y, patch_size, width, height):
    motion_cost = np.zeros((max_motion_x*2-1, max_motion_y*2-1))
    point1 = edge_points1[point_id1]
    max_shift_x = max_motion_x + patch_size // 2
    max_shift_y = max_motion_y + patch_size // 2
    if point1[0] - max_shift_x < 0 or point1[1] - max_shift_y < 0 \
            or point1[0] + max_shift_x > height or point1[1] + max_shift_y > width:
                return motion_cost
    for motion_x in range(-max_motion_x+1, max_motion_x):
        for motion_y in range(-max_motion_y+1, max_motion_y):
            motion_cost[motion_x+max_motion_x-1, motion_y+max_motion_y-1] = get_patch_pixel_diff(I1, I2, edge_points1, edge_points2, point_id1, motion_x, motion_y, patch_size)
    return motion_cost

def get_smoothness_penalty(self_motion_field, neighbor_motion_field, penalty_constant=0.005):
    return penalty_constant * (abs(self_motion_field[0] - neighbor_motion_field[0]) + abs(self_motion_field[1] - neighbor_motion_field[1]))

def min_sum(self_motion_fields, neighbor_messages, max_motion_x, max_motion_y):
    message_matrix = np.zeros((max_motion_x*2-1, max_motion_y*2-1))
    neighbor_contribution = np.zeros((max_motion_x*2-1, max_motion_y*2-1))
    for neighbor_message in neighbor_messages:
        neighbor_contribution += neighbor_message

    for motion_x1 in range(-max_motion_x+1, max_motion_x): # message recipient motion 
        for motion_y1 in range(-max_motion_y+1, max_motion_y): 
            min_message = float("inf")
            for motion_x2 in range(-max_motion_x+1, max_motion_x): # own motion
                for motion_y2 in range(-max_motion_y+1, max_motion_y):
                    possible_val = self_motion_fields[motion_x2+max_motion_x-1][motion_y2+max_motion_y-1] + get_smoothness_penalty((motion_x1, motion_y1), (motion_x2, motion_y2)) + neighbor_contribution[motion_x2+max_motion_x-1][motion_y2+max_motion_y-1]
                    min_message = min(min_message, possible_val)
            message_matrix[motion_x1+max_motion_x-1, motion_y1+max_motion_y-1] = possible_val
    # maybe no need.
    # message_matrix = message_matrix - np.log(np.exp(message_matrix).sum())
    return message_matrix

directions = [[1, 0], [0, 1], [0, -1], [-1, 0]]
def pass_message(motion_fields, point_number, edge_points1, edge_points1_map, message_passing_rounds, width, height, max_motion_x, max_motion_y):
    message_map = np.zeros((point_number, 4, max_motion_x*2-1, max_motion_y*2-1))
    next_message_map = np.zeros((point_number, 4, max_motion_x*2-1, max_motion_y*2-1))
    for m_round in range(message_passing_rounds):
        print('m_round: ', m_round)
        # means message `from` some direction.
        for d in range(4):
            direction = directions[d]
            for point_id in range(point_number):
                point1 = edge_points1[point_id]
                # exclude the message from the neighbor we are passing to.
                point_new = (point1[0]+direction[0], point1[1]+direction[1])
                if point_new in edge_points1_map:
                    neighbor_messages = []
                    for i in range(4):
                        if i != d:
                            point_new_tmp = (point1[0]+directions[i][0], point1[1]+directions[i][1])
                            if point_new_tmp in edge_points1_map:
                                neighbor_messages.append(message_map[point_id, i])
                    if len(neighbor_messages) != 3:
                        continue
                    # populate the new message map with the next round's messages 
                    next_message_map[edge_points1_map[point_new], 3-d] = min_sum(motion_fields[point_id], neighbor_messages, max_motion_x, max_motion_y)
        message_map = next_message_map
    return message_map

def get_belief(motion_fields, message_map, edge_points1, edge_points1_map, point_number, max_motion_x, max_motion_y):
    final_motion_fields = np.zeros((point_number, 2))
    for point_id in range(point_number):
        point1 = edge_points1[point_id]
        best_motion = (0, 0)
        best_motion_belief = 0.
        for motion_x in range(-max_motion_x+1, max_motion_x):
            for motion_y in range(-max_motion_y+1,max_motion_y):
                data_cost = motion_fields[point_id][motion_x + max_motion_x-1][motion_y + max_motion_y - 1]
                neighbor_belief = 0.
                neighbors = message_map[point_id]
                for i in range(4):
                    point_new_tmp = (point1[0]+directions[i][0], point1[1]+directions[i][1])
                    if point_new_tmp in edge_points1_map:
                        neighbor_belief += neighbors[i][motion_x+max_motion_x-1][motion_y+max_motion_y-1]
                import IPython
                IPython.embed()
                belief = data_cost + neighbor_belief
                if belief < best_motion_belief:
                    best_motion_belief = belief
                    best_motion = (motion_x, motion_y)
        final_motion_fields[point_id] = best_motion
    return final_motion_fields

def produce_motion_fields(I1, I2, edge_image1, edge_image2, height, width, patch_size, max_motion_x, max_motion_y, message_passing_rounds):
    edge_points1 = np.argwhere(edge_image1)
    edge_points2 = np.argwhere(edge_image2)
    point_number = len(edge_points1)
    motion_fields = np.zeros((point_number, max_motion_x*2-1, max_motion_y*2-1))

    edge_points1_map = {}
    for point_id in range(point_number):
        motion_fields[point_id, :, :] = get_cost_by_motion(I1, I2, edge_points1, edge_points2, point_id, max_motion_x, max_motion_y, patch_size, width, height)
        edge_points1_map[tuple(edge_points1[point_id])] = point_id

    message_map = pass_message(motion_fields, point_number, edge_points1, edge_points1_map, message_passing_rounds, width, height, max_motion_x,max_motion_y)
    final_motion_fields = get_belief(motion_fields, message_map, edge_points1, edge_points1_map, point_number, max_motion_x, max_motion_y)
    return final_motion_fields, edge_points1, edge_points1_map

edgeI2 = cv2.imread('./test_image/edges0.png', 0)
edgeI1 = cv2.imread('./test_image/edges2.png',0)
I2 = cv2.imread('./test_image/hanoi_input_1.png', 0)
I1 = cv2.imread('./test_image/hanoi_input_3.png', 0)
I1 = I1 / 255.
I2 = I2 / 255.

height, width = edgeI1.shape
height, width = height//2, width//2
edgeI2 = cv2.resize(edgeI2, (width, height))
edgeI1 = cv2.resize(edgeI1, (width, height))
I2 = cv2.resize(I2, (width, height))
I1 = cv2.resize(I1, (width, height))
patch_size = 5
max_motion_x = 25
max_motion_y = 25
message_passing_rounds = 5
final_motion_fields, edge_points1, edge_points1_map = produce_motion_fields(I1, I2, edgeI1, edgeI2, height, width, patch_size, max_motion_x, max_motion_y, message_passing_rounds)
visualized_motion_fields = np.zeros((height, width, 3), dtype=np.uint8)
for point_id, motion_field in enumerate(final_motion_fields):
    point_pos = edge_points1[point_id]
    visualized_motion_fields[point_pos[0], point_pos[1], 0] = np.uint8((final_motion_fields[point_id, 0]+max_motion_x) * 255. / (max_motion_x * 2 - 1))
    visualized_motion_fields[point_pos[0], point_pos[1], 1] = np.uint8((final_motion_fields[point_id, 1]+max_motion_y) * 255. / (max_motion_y * 2 - 1))
    cv2.imshow('motion_fields', visualized_motion_fields)
    cv2.waitKey(0)