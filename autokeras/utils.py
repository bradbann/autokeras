import os
import pickle
import numpy as np

from keras.callbacks import Callback, LearningRateScheduler, ReduceLROnPlateau
from keras.losses import categorical_crossentropy
from keras.layers import Conv1D, Conv2D, Conv3D, MaxPooling3D, MaxPooling2D, MaxPooling1D, Dense, BatchNormalization, \
    Concatenate, Dropout, Activation, Flatten, GlobalAveragePooling1D, GlobalAveragePooling2D, GlobalAveragePooling3D
from keras.optimizers import Adam
from keras.preprocessing.image import ImageDataGenerator
from tensorflow import Dimension

from autokeras import constant
from autokeras.constant import CONV_FUNC_LIST
from autokeras.layers import StubConv, StubDense, StubBatchNormalization, StubConcatenate, StubWeightedAdd, \
    WeightedAdd, StubPooling, StubDropout, StubActivation, StubFlatten, StubGlobalPooling


def is_conv_layer(layer):
    """Return whether the layer is convolution layer"""
    return isinstance(layer, tuple(CONV_FUNC_LIST))


def is_dense_layer(layer):
    return isinstance(layer, Dense)


def get_conv_layer_func(n_dim):
    """Return convolution function based on the dimension"""
    conv_layer_functions = [Conv1D, Conv2D, Conv3D]
    if n_dim > 3:
        raise ValueError('The input dimension is too high.')
    if n_dim < 1:
        raise ValueError('The input dimension is too low.')
    return conv_layer_functions[n_dim - 1]


def get_ave_layer_func(n_dim):
    """Return convolution function based on the dimension"""
    conv_layer_functions = [GlobalAveragePooling1D, GlobalAveragePooling2D, GlobalAveragePooling3D]
    if n_dim > 3:
        raise ValueError('The input dimension is too high.')
    if n_dim < 1:
        raise ValueError('The input dimension is too low.')
    return conv_layer_functions[n_dim - 1]


def lr_schedule(epoch):
    """Learning Rate Schedule

    Learning rate is scheduled to be reduced after 80, 120, 160, 180 epochs.
    Called automatically every epoch as part of callbacks during training.

    # Arguments
        epoch (int): The number of epochs

    # Returns
        lr (float32): learning rate
    """
    lr = 1e-3
    if epoch > 180:
        lr *= 0.5e-3
    elif epoch > 160:
        lr *= 1e-3
    elif epoch > 120:
        lr *= 1e-2
    elif epoch > 80:
        lr *= 1e-1
    return lr


class NoImprovementError(Exception):
    def __init__(self, message):
        self.message = message


class EarlyStop(Callback):
    def __init__(self, max_no_improvement_num=constant.MAX_NO_IMPROVEMENT_NUM, min_loss_dec=constant.MIN_LOSS_DEC):
        super().__init__()
        self.training_losses = []
        self.minimum_loss = None
        self._no_improvement_count = 0
        self._max_no_improvement_num = max_no_improvement_num
        self._done = False
        self._min_loss_dec = min_loss_dec
        self.max_accuracy = 0

    def on_train_begin(self, logs=None):
        self.training_losses = []
        self._no_improvement_count = 0
        self._done = False
        self.minimum_loss = float('inf')

    def on_epoch_end(self, batch, logs=None):
        # self.max_accuracy = max(self.max_accuracy, logs.get('val_acc'))
        self.max_accuracy = logs.get('val_acc')
        loss = logs.get('val_loss')
        self.training_losses.append(loss)
        if self._done and loss > (self.minimum_loss - self._min_loss_dec):
            raise NoImprovementError('No improvement for {} epochs.'.format(self._max_no_improvement_num))

        if loss > (self.minimum_loss - self._min_loss_dec):
            self._no_improvement_count += 1
        else:
            self._no_improvement_count = 0
            self.minimum_loss = loss

        if self._no_improvement_count > self._max_no_improvement_num:
            self._done = True


class ModelTrainer:
    """A class that is used to train model

    This class can train a model with dataset and will not stop until getting minimum loss

    Attributes:
        model: the model that will be trained
        x_train: the input train data
        y_train: the input train data labels
        x_test: the input test data
        y_test: the input test data labels
        verbose: verbosity mode
    """

    def __init__(self, model, x_train, y_train, x_test, y_test, verbose):
        """Init ModelTrainer with model, x_train, y_train, x_test, y_test, verbose"""
        self.model = model
        self.x_train = x_train
        self.y_train = y_train
        self.x_test = x_test
        self.y_test = y_test
        self.verbose = verbose

    def train_model(self,
                    max_iter_num=constant.MAX_ITER_NUM,
                    max_no_improvement_num=constant.MAX_NO_IMPROVEMENT_NUM,
                    batch_size=constant.MAX_BATCH_SIZE,
                    optimizer=None,
                    augment=constant.DATA_AUGMENTATION):
        if augment:
            datagen = ImageDataGenerator(
                # set input mean to 0 over the dataset
                featurewise_center=False,
                # set each sample mean to 0
                samplewise_center=False,
                # divide inputs by std of dataset
                featurewise_std_normalization=False,
                # divide each input by its std
                samplewise_std_normalization=False,
                # apply ZCA whitening
                zca_whitening=False,
                # randomly rotate images in the range (deg 0 to 180)
                rotation_range=0,
                # randomly shift images horizontally
                width_shift_range=0.1,
                # randomly shift images vertically
                height_shift_range=0.1,
                # randomly flip images
                horizontal_flip=True,
                # randomly flip images
                vertical_flip=False)
            datagen.fit(self.x_train)
        else:
            datagen = None
        if optimizer is None:
            self.model.compile(loss=categorical_crossentropy,
                               optimizer=Adam(lr=lr_schedule(0)),
                               metrics=['accuracy'])
        else:
            self.model.compile(loss=categorical_crossentropy,
                               optimizer=optimizer(),
                               metrics=['accuracy'])
        """Train the model with dataset and return the minimum_loss"""
        batch_size = min(self.x_train.shape[0], batch_size)
        terminator = EarlyStop(max_no_improvement_num=max_no_improvement_num)
        lr_scheduler = LearningRateScheduler(lr_schedule)

        lr_reducer = ReduceLROnPlateau(factor=np.sqrt(0.1),
                                       cooldown=0,
                                       patience=5,
                                       min_lr=0.5e-6)

        callbacks = [terminator, lr_scheduler, lr_reducer]
        try:
            if augment:
                flow = datagen.flow(self.x_train, self.y_train, batch_size)
                self.model.fit_generator(flow,
                                         epochs=max_iter_num,
                                         validation_data=(self.x_test, self.y_test),
                                         callbacks=callbacks,
                                         verbose=self.verbose)
            else:
                self.model.fit(self.x_train, self.y_train,
                               batch_size=batch_size,
                               epochs=max_iter_num,
                               validation_data=(self.x_test, self.y_test),
                               callbacks=callbacks,
                               verbose=self.verbose)
        except NoImprovementError as e:
            if self.verbose:
                print('Training finished!')
                print(e.message)
            return terminator.minimum_loss, terminator.max_accuracy
        return terminator.minimum_loss, terminator.max_accuracy


def extract_config(network):
    """Return configuration of one model"""
    return network.get_config()


def ensure_dir(directory):
    """Create directory if it does not exist"""
    if not os.path.exists(directory):
        os.makedirs(directory)


def ensure_file_dir(path):
    """Create path if it does not exist"""
    ensure_dir(os.path.dirname(path))


def has_file(path):
    """Return whether the path has a file"""
    return os.path.exists(path)


def get_int_tuple(temp_shape):
    """Return the input shape of temp_shape in the form of tuple"""
    input_shape = []
    for i in temp_shape:
        if isinstance(i, Dimension):
            input_shape.append(i.value)
        else:
            input_shape.append(i)
    return tuple(input_shape)


def is_pooling_layer(layer):
    return isinstance(layer, (MaxPooling1D, MaxPooling2D, MaxPooling3D))


def is_global_pooling_layer(layer):
    return isinstance(layer, (GlobalAveragePooling1D, GlobalAveragePooling2D, GlobalAveragePooling3D))


def pickle_from_file(path):
    return pickle.load(open(path, 'rb'))


def pickle_to_file(obj, path):
    pickle.dump(obj, open(path, 'wb'))


def is_layer(layer, layer_type):
    if layer_type == 'Conv':
        return isinstance(layer, StubConv) or is_conv_layer(layer)
    if layer_type == 'Dense':
        return isinstance(layer, (StubDense, Dense))
    if layer_type == 'BatchNormalization':
        return isinstance(layer, (StubBatchNormalization, BatchNormalization))
    if layer_type == 'Concatenate':
        return isinstance(layer, (StubConcatenate, Concatenate))
    if layer_type == 'WeightedAdd':
        return isinstance(layer, (StubWeightedAdd, WeightedAdd))
    if layer_type == 'Pooling':
        return isinstance(layer, StubPooling) or is_pooling_layer(layer)
    if layer_type == 'Dropout':
        return isinstance(layer, (StubDropout, Dropout))
    if layer_type == 'Activation':
        return isinstance(layer, (StubActivation, Activation))
    if layer_type == 'Flatten':
        return isinstance(layer, (StubFlatten, Flatten))
    if layer_type == 'GlobalAveragePooling':
        return isinstance(layer, StubGlobalPooling) or is_global_pooling_layer(layer)


def layer_width(layer):
    if is_layer(layer, 'Dense'):
        return layer.units
    if is_layer(layer, 'Conv'):
        return layer.filters
    raise TypeError('The layer should be either Dense or Conv layer.')
