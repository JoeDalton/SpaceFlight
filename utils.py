import quaternion
import numpy as np

def rotate_single_vector(quat: np.quaternion, vector: np.ndarray):
    """
    Rotates vector by the rotation defined by quat
    """
    # TODO quaternion multiplication for faster computation
    return quaternion.rotate_vectors(quat, vector)