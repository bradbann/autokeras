from keras.layers import Conv3D, Conv2D, Conv1D, Dense

from autokeras.layers import StubDense, StubConv

CONV_FUNC_LIST = [Conv1D, Conv2D, Conv3D, StubConv]
WEIGHTED_LAYER_FUNC_LIST = CONV_FUNC_LIST + [Dense, StubDense]
DEFAULT_SAVE_PATH = '/tmp/autokeras/'


# Searcher

MAX_MODEL_NUM = 1000
BETA = 2.576
KERNEL_LAMBDA = 1.0
T_MIN = 0.0001

# Model Defaults

DENSE_DROPOUT_RATE = 0.5
CONV_DROPOUT_RATE = 0.25
CONV_BLOCK_DISTANCE = 2
DENSE_BLOCK_DISTANCE = 2
MODEL_LEN = 4
MODEL_WIDTH = 256

# ModelTrainer

DATA_AUGMENTATION = True
MAX_ITER_NUM = 200
MIN_LOSS_DEC = 1e-4
MAX_NO_IMPROVEMENT_NUM = 100
MAX_BATCH_SIZE = 32
LIMIT_MEMORY = False
SEARCH_MAX_ITER = 30
