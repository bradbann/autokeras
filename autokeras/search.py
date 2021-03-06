import os
import random
from functools import total_ordering
from queue import PriorityQueue

import numpy as np
import math

from keras.models import load_model
from keras import backend
from keras.utils import plot_model

from autokeras import constant
from autokeras.bayesian import IncrementalGaussianProcess
from autokeras.generator import RandomConvClassifierGenerator, DefaultClassifierGenerator
from autokeras.graph import Graph
from autokeras.layers import WeightedAdd
from autokeras.net_transformer import transform
from autokeras.utils import ModelTrainer, pickle_to_file
from autokeras.utils import extract_config


class Searcher:
    """Base class of all searcher class

    This class is the base class of all searcher class,
    every searcher class can override its search function
    to implements its strategy

    Attributes:
        n_classes: number of classification
        input_shape: Arbitrary, although all dimensions in the input shaped must be fixed.
                   Use the keyword argument input_shape (tuple of integers, does not include the batch axis)
                   when using this layer as the first layer in a model.
        verbose: verbosity mode
        history_configs: a list that stores all historical configuration
        history: a list that stores the performance of model
        path: place that store searcher
        model_count: the id of model
    """

    def __init__(self, n_classes, input_shape, path, verbose,
                 trainer_args=None,
                 default_model_len=constant.MODEL_LEN,
                 default_model_width=constant.MODEL_WIDTH):
        """Init Searcher class with n_classes, input_shape, path, verbose

        The Searcher will be loaded from file if it has been saved before.
        """
        if trainer_args is None:
            trainer_args = {}
        self.n_classes = n_classes
        self.input_shape = input_shape
        self.verbose = verbose
        self.history_configs = []
        self.history = []
        self.path = path
        self.model_count = 0
        self.descriptors = {}
        self.trainer_args = trainer_args
        self.default_model_len = default_model_len
        self.default_model_width = default_model_width
        if 'max_iter_num' not in self.trainer_args:
            self.trainer_args['max_iter_num'] = constant.SEARCH_MAX_ITER

    def search(self, x_train, y_train, x_test, y_test):
        """an search strategy that will be overridden by children classes"""
        pass

    def load_model_by_id(self, model_id):
        return load_model(os.path.join(self.path, str(model_id) + '.h5'), {'WeightedAdd': WeightedAdd})

    def load_best_model(self):
        """return model with best accuracy"""
        return self.load_model_by_id(self.get_best_model_id())

    def get_accuracy_by_id(self, model_id):
        for item in self.history:
            if item['model_id'] == model_id:
                return item['accuracy']
        return None

    def get_best_model_id(self):
        return max(self.history, key=lambda x: x['accuracy'])['model_id']

    def replace_model(self, model, model_id):
        model.save(os.path.join(self.path, str(model_id) + '.h5'))

    def add_model(self, model, x_train, y_train, x_test, y_test):
        """add one model while will be trained to history list

        Returns:
            History object.
        """
        loss, accuracy = ModelTrainer(model,
                                      x_train,
                                      y_train,
                                      x_test,
                                      y_test,
                                      False).train_model(**self.trainer_args)

        accuracy += 0.005 * len(Graph(model, False).extract_descriptor().skip_connections)
        accuracy = min(accuracy, 1)

        model.save(os.path.join(self.path, str(self.model_count) + '.h5'))
        plot_model(model, to_file=os.path.join(self.path, str(self.model_count) + '.png'), show_shapes=True)

        model_id = self.model_count
        ret = {'model_id': model_id, 'loss': loss, 'accuracy': accuracy}
        self.history.append(ret)
        self.history_configs.append(extract_config(model))
        self.model_count += 1
        self.descriptors[Graph(model, False).extract_descriptor()] = True

        # Update best_model text file
        if model_id == self.get_best_model_id():
            file = open(os.path.join(self.path, 'best_model.txt'), 'w')
            file.write('best model: ' + str(model_id))
            file.close()

        if self.verbose:
            print('Model ID:', model_id)
            print('Loss:', loss)
            print('Accuracy', accuracy)
        return ret


class RandomSearcher(Searcher):
    """Random Searcher class inherited from ClassifierBase class

    RandomSearcher implements its search function with random strategy
    """

    def __init__(self, n_classes, input_shape, path, verbose):
        """Init RandomSearcher with n_classes, input_shape, path, verbose"""
        super().__init__(n_classes, input_shape, path, verbose)

    def search(self, x_train, y_train, x_test, y_test):
        """Override parent's search function. First model is randomly generated"""
        while self.model_count < constant.MAX_MODEL_NUM:
            model = RandomConvClassifierGenerator(self.n_classes, self.input_shape).generate()
            self.add_model(model, x_train, y_train, x_test, y_test)
            pickle_to_file(self, os.path.join(self.path, 'searcher'))
            backend.clear_session()

        return self.load_best_model()


class HillClimbingSearcher(Searcher):
    """HillClimbing Searcher class inherited from ClassifierBase class

    HillClimbing Searcher implements its search function with hill climbing strategy
    """

    def __init__(self, n_classes, input_shape, path, verbose):
        """Init HillClimbing Searcher with n_classes, input_shape, path, verbose"""
        super().__init__(n_classes, input_shape, path, verbose)

    def _remove_duplicate(self, models):
        """Remove the duplicate in the history_models"""
        ans = []
        for model_a in models:
            model_a_config = extract_config(model_a)
            if model_a_config not in self.history_configs:
                ans.append(model_a)
        return ans

    def search(self, x_train, y_train, x_test, y_test):
        """Override parent's search function. First model is randomly generated"""
        if not self.history:
            model = DefaultClassifierGenerator(self.n_classes, self.input_shape).generate()
            self.add_model(model, x_train, y_train, x_test, y_test)
            pickle_to_file(self, os.path.join(self.path, 'searcher'))

        else:
            model = self.load_best_model()
            new_graphs = transform(Graph(model, False))
            new_models = []
            for graph in new_graphs:
                nm_graph = Graph(model, True)
                for args in graph.operation_history:
                    getattr(nm_graph, args[0])(*list(args[1:]))
                    new_models.append(nm_graph.produce_model())
            new_models = self._remove_duplicate(list(new_models))

            for model in new_models:
                if self.model_count < constant.MAX_MODEL_NUM:
                    self.add_model(model, x_train, y_train, x_test, y_test)
                    pickle_to_file(self, os.path.join(self.path, 'searcher'))

            backend.clear_session()

        return self.load_best_model()


class BayesianSearcher(Searcher):

    def __init__(self, n_classes, input_shape, path, verbose,
                 trainer_args=None,
                 default_model_len=constant.MODEL_LEN,
                 default_model_width=constant.MODEL_WIDTH,
                 beta=constant.BETA,
                 kernel_lambda=constant.KERNEL_LAMBDA,
                 t_min=constant.T_MIN):
        super().__init__(n_classes, input_shape, path, verbose, trainer_args, default_model_len, default_model_width)
        self.gpr = IncrementalGaussianProcess(kernel_lambda)
        self.search_tree = SearchTree()
        self.init_search_queue = None
        self.init_gpr_x = []
        self.init_gpr_y = []
        self.beta = beta
        self.t_min = t_min

    def search(self, x_train, y_train, x_test, y_test):
        if not self.history:
            model = DefaultClassifierGenerator(self.n_classes,
                                               self.input_shape).generate(self.default_model_len,
                                                                          self.default_model_width)
            history_item = self.add_model(model, x_train, y_train, x_test, y_test)
            self.search_tree.add_child(-1, history_item['model_id'])

            graph = Graph(model)
            self.init_search_queue = []
            # for child_graph in transform(graph):
            #     self.init_search_queue.append((child_graph, history_item['model_id']))
            self.init_gpr_x.append(graph.extract_descriptor())
            self.init_gpr_y.append(history_item['accuracy'])
            pickle_to_file(self, os.path.join(self.path, 'searcher'))
            return

        if self.init_search_queue:
            graph, father_id = self.init_search_queue.pop()
            model = graph.produce_model()
            history_item = self.add_model(model, x_train, y_train, x_test, y_test)
            self.search_tree.add_child(father_id, history_item['model_id'])
            self.init_gpr_x.append(graph.extract_descriptor())
            self.init_gpr_y.append(history_item['accuracy'])
            pickle_to_file(self, os.path.join(self.path, 'searcher'))
            return

        if not self.init_search_queue and not self.gpr.first_fitted:
            self.gpr.first_fit(self.init_gpr_x, self.init_gpr_y)

        new_model, father_id = self.maximize_acq()

        history_item = self.add_model(new_model, x_train, y_train, x_test, y_test)
        self.search_tree.add_child(father_id, history_item['model_id'])
        self.gpr.incremental_fit(Graph(new_model).extract_descriptor(), history_item['accuracy'])
        pickle_to_file(self, os.path.join(self.path, 'searcher'))

    def maximize_acq(self):
        model_ids = self.search_tree.adj_list.keys()
        target_graph = None
        father_id = None
        descriptors = self.descriptors

        pq = PriorityQueue()
        temp_list = []
        for model_id in model_ids:
            accuracy = self.get_accuracy_by_id(model_id)
            temp_list.append((accuracy, model_id))
        temp_list = sorted(temp_list)
        if len(temp_list) > 5:
            temp_list = temp_list[:-5]
        for accuracy, model_id in temp_list:
            model = self.load_model_by_id(model_id)
            graph = Graph(model, False)
            pq.put(Elem(accuracy, model_id, graph))

        t = 1.0
        t_min = self.t_min
        alpha = 0.9
        max_acq = -1
        while not pq.empty() and t > t_min:
            elem = pq.get()
            ap = math.exp((elem.accuracy - max_acq) / t)
            if ap > random.uniform(0, 1):
                graphs = transform(elem.graph)
                graphs = list(filter(lambda x: x.extract_descriptor() not in descriptors, graphs))
                if not graphs:
                    continue
                for temp_graph in graphs:
                    temp_acq_value = self.acq(temp_graph)
                    pq.put(Elem(temp_acq_value, elem.father_id, temp_graph))
                    descriptors[temp_graph.extract_descriptor()] = True
                    if temp_acq_value > max_acq:
                        max_acq = temp_acq_value
                        father_id = elem.father_id
                        target_graph = temp_graph
            t *= alpha

        model = self.load_model_by_id(father_id)
        nm_graph = Graph(model, True)
        if self.verbose:
            print('Father ID: ', father_id)
            print(target_graph.operation_history)
        for args in target_graph.operation_history:
            getattr(nm_graph, args[0])(*list(args[1:]))
        return nm_graph.produce_model(), father_id

    def acq(self, graph):
        mean, std = self.gpr.predict(np.array([graph.extract_descriptor()]))
        return mean + self.beta * std


class SearchTree:
    def __init__(self):
        self.root = None
        self.adj_list = {}

    def add_child(self, u, v):
        if u == -1:
            self.root = v
            self.adj_list[v] = []
            return
        if v not in self.adj_list[u]:
            self.adj_list[u].append(v)
        if v not in self.adj_list:
            self.adj_list[v] = []

    def get_leaves(self):
        ret = []
        for key, value in self.adj_list.items():
            if not value:
                ret.append(key)
        return ret


@total_ordering
class Elem:
    def __init__(self, accuracy, father_id, graph):
        self.father_id = father_id
        self.graph = graph
        self.accuracy = accuracy

    def __eq__(self, other):
        return self.accuracy == other.accuracy

    def __lt__(self, other):
        return self.accuracy < other.accuracy
