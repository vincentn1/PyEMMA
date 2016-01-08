# This file is part of PyEMMA.
#
# Copyright (c) 2015, 2014 Computational Molecular Biology Group, Freie Universitaet Berlin (GER)
#
# PyEMMA is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from __future__ import absolute_import

from abc import ABCMeta, abstractmethod

import numpy as np
import six
from six.moves import range

from pyemma._base.estimator import Estimator
from pyemma._base.logging import Loggable
from pyemma.coordinates.data import DataInMemory
from pyemma.coordinates.data.datasource import DataSource, DataSourceIterator
from pyemma.coordinates.data.iterable import Iterable
from pyemma.util import types as _types
from pyemma.util.annotators import deprecated
from pyemma.util.exceptions import NotConvergedWarning
from pyemma._base.progress.reporter import ProgressReporter

__all__ = ['Transformer']
__author__ = 'noe, marscher'


def _to_data_producer(X):
    # this is a pipelining stage, so let's parametrize from it
    if isinstance(X, Transformer):
        inputstage = X
    # second option: data is array or list of arrays
    else:
        data = _types.ensure_traj_list(X)
        inputstage = DataInMemory(data)

    return inputstage


class Transformer(six.with_metaclass(ABCMeta, DataSource, Estimator, Loggable)):
    r""" Basis class for pipeline objects

    Parameters
    ----------
    chunksize : int (optional)
        the chunksize used to batch process underlying data

    """

    def __init__(self, chunksize=1000):
        super(Transformer, self).__init__(chunksize=chunksize)
        self._data_producer = None
        self._estimated = False

    def _create_iterator(self, skip=0, chunk=0, stride=1, return_trajindex=True):
        return TransformerIterator(self, skip=skip, chunk=chunk, stride=stride,
                                   return_trajindex=return_trajindex)

    @property
    def data_producer(self):
        r"""where the transformer obtains its data."""
        return self._data_producer

    @data_producer.setter
    def data_producer(self, dp):
        if dp is not self._data_producer:
            self._logger.debug("reset (previous) parametrization state, since"
                               " data producer has been changed.")
            self._estimated = False
        self._data_producer = dp

    #@Iterable.chunksize
    def chunksize(self):
        """chunksize defines how much data is being processed at once."""
        return self.data_producer.chunksize

    @Iterable.chunksize.setter
    def chunksize(self, size):
        if not size >= 0:
            raise ValueError("chunksize has to be positive")

        self.data_producer.chunksize = int(size)

    def number_of_trajectories(self):
        r"""
        Returns the number of trajectories.

        Returns
        -------
            int : number of trajectories
        """
        return self.data_producer.number_of_trajectories()

    def trajectory_length(self, itraj, stride=1, skip=None):
        r"""
        Returns the length of trajectory of the requested index.

        Parameters
        ----------
        itraj : int
            trajectory index
        stride : int
            return value is the number of frames in the trajectory when
            running through it with a step size of `stride`.

        Returns
        -------
        int : length of trajectory
        """
        return self.data_producer.trajectory_length(itraj, stride=stride, skip=skip)

    def trajectory_lengths(self, stride=1, skip=0):
        r"""
        Returns the length of each trajectory.

        Parameters
        ----------
        stride : int
            return value is the number of frames of the trajectories when
            running through them with a step size of `stride`.
        skip : int
            skip parameter

        Returns
        -------
        array(dtype=int) : containing length of each trajectory
        """
        return self.data_producer.trajectory_lengths(stride=stride, skip=skip)

    def n_frames_total(self, stride=1):
        r"""
        Returns total number of frames.

        Parameters
        ----------
        stride : int
            return value is the number of frames in trajectories when
            running through them with a step size of `stride`.

        Returns
        -------
        int : n_frames_total
        """
        return self.data_producer.n_frames_total(stride=stride)

    @abstractmethod
    def describe(self):
        r""" Get a descriptive string representation of this class."""
        pass

    def fit(self, X, **kwargs):
        r"""For compatibility with sklearn"""
        self.data_producer = _to_data_producer(X)
        self.estimate(X, **kwargs)
        return self

    def fit_transform(self, X, **kwargs):
        r"""For compatibility with sklearn"""
        self.fit(X, **kwargs)
        return self.transform(X)

    def estimate(self, X, **kwargs):
        if not isinstance(X, Iterable):
            if isinstance(X, np.ndarray):
                X = DataInMemory(X, self.chunksize)
                self.data_producer = X
            else:
                raise ValueError("no array given")

        model = None
        # for backward-compat
        if hasattr(self, '_param_init'):
            self._param_init(**kwargs)
        # run estimation
        try:
            model = super(Transformer, self).estimate(X, **kwargs)
        except NotConvergedWarning as ncw:
            self._logger.info("Presumely finished estimation. Message: %s" % ncw)
        # finish
        if hasattr(self, '_param_finish'):
            self._param_finish()
        # memory mode? Then map all results. Avoid recursion here, if parametrization
        # is triggered from get_output
        if self.in_memory and not self._mapping_to_mem_active:
            self._map_to_memory()

        self._estimated = True

        return model

    def get_output(self, dimensions=slice(0, None), stride=1, skip=0, chunk=0):
        if not self._estimated:
            self.estimate(self.data_producer, stride=stride)

        return super(Transformer, self).get_output(dimensions, stride, skip, chunk)

    # TODO: re-enable this warning, as soon as all tests pass
    #@deprecated("Please use estimate")
    def parametrize(self, stride=1):
        if self._data_producer is None:
            raise RuntimeError("This estimator has no data source given, giving up.")

        return self.estimate(self.data_producer, stride=stride)

    @deprecated("use fit.")
    def transform(self, X):
        r"""Maps the input data through the transformer to correspondingly
        shaped output data array/list.

        Parameters
        ----------
        X : ndarray(T, n) or list of ndarray(T_i, n)
            The input data, where T is the number of time steps and n is the
            number of dimensions.
            If a list is provided, the number of time steps is allowed to vary,
            but the number of dimensions are required to be to be consistent.

        Returns
        -------
        Y : ndarray(T, d) or list of ndarray(T_i, d)
            The mapped data, where T is the number of time steps of the input
            data and d is the output dimension of this transformer. If called
            with a list of trajectories, Y will also be a corresponding list of
            trajectories
        """
        if isinstance(X, np.ndarray):
            if X.ndim == 2:
                mapped = self._transform_array(X)
                return mapped
            else:
                raise TypeError('Input has the wrong shape: %s with %i'
                                ' dimensions. Expecting a matrix (2 dimensions)'
                                % (str(X.shape), X.ndim))
        elif isinstance(X, (list, tuple)):
            out = []
            for x in X:
                mapped = self._transform_array(x)
                out.append(mapped)
            return out
        else:
            raise TypeError('Input has the wrong type: %s '
                            '. Either accepting numpy arrays of dimension 2 '
                            'or lists of such arrays' % (str(type(X))))

    @abstractmethod
    def _transform_array(self, X):
        r"""
        Initializes the parametrization.

        Parameters
        ----------
        X : ndarray(T, n)
            The input data, where T is the number of time steps and 
            n is the number of dimensions.

        Returns
        -------
        Y : ndarray(T, d)
            The projected data, where T is the number of time steps of the 
            input data and d is the output dimension of this transformer.

        """
        pass

#     def __getstate__(self):
#         state = super(Transformer, self).__getstate__()
#         print ("getstate transformer", state)
#         not_to_pickle = ('_data_producer', )
#         for k in not_to_pickle:
#             state.pop(k, None)
#         return state


class TransformerIterator(DataSourceIterator):

    def __init__(self, data_source, skip=0, chunk=0, stride=1, return_trajindex=False):
        super(TransformerIterator, self).__init__(data_source, return_trajindex=return_trajindex)
        self._it = self._data_source.data_producer._create_iterator(
                skip=skip, chunk=chunk, stride=stride, return_trajindex=return_trajindex
        )
        self.state = self._it.state

    @property
    def _n_chunks(self):
        return self._it._n_chunks

    def close(self):
        self._it.close()

    @property
    def current_trajindex(self):
        return self._it.current_trajindex

    def next_chunk(self):
        X = self._it.next_chunk()
        return self._data_source._transform_array(X)
