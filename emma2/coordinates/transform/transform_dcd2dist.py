'''
Created on Nov 16, 2013

@author: noe
'''

import os
import filetransform
from emma2.util.pystallone import *

class Transform_dcd2dist(filetransform.FileTransform):

    # Atom set 1
    _set1 = JArray_int([0])
    _set2 = JArray_int([1])

    def __init__(self, set1, set2=None):
        """
        input_directory: directory with input data files
        tica_directory: directory to store covariance and mean files
        output_directory: directory to write transformed data files to
        lag: TICA lagtime
        ndim: number of TICA dimensions to use
        """
        # define sets for the distance computation
        self._set1 = jarray(set1)
        if (set2 is None):
            self._set2 = jarray(set1)
        else:
            self._set2 = jarray(set2)


    def transform(self, infile, outfile):
        """
        Transform individual file
        """
        API.coor.convertToDistances(infile, outfile, self._set1, self._set2)