###############################################################################
#
# Authors: C. Pradal, Y. Boursiac
# Date : 14/10/2016
#
# Date: 2019-12-03
# Modified by F. Bauget to test yaml configuration file
#
# Date: 2019-12-10
# F. Bauget merging simulation.py and hydro_measures
###############################################################################

######
# Imports

# VERSION = 2

from random import _hexlify, _urandom

import numpy as np
import pandas as pd
import glob
import copy
import argparse

import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.colors import Normalize

from openalea.mtg import traversal
from openalea.plantgl.all import Viewer
from openalea.mtg.algo import axis


from hydroroot import radius, markov
from hydroroot.law import histo_relative_law, reference_relative_law
from hydroroot.generator.measured_root import mtg_from_aqua_data
from hydroroot.analysis import intercept
from hydroroot.main import hydroroot_flow
from hydroroot.init_parameter import Parameters  # import work in progress for reading init file
from hydroroot.display import plot as mtg_scene

ONE_LAW = False
EXPOVARIATE = True
results = {}

################################################
# get the model parameters, the length laws are
# calculated from the files given in the yaml file
###############################################

parameter = Parameters()
# parameter.read_file('../example/parameters.yml')

parser = argparse.ArgumentParser()
parser.add_argument("inputfile", help="yaml input file")
parser.add_argument("-o", "--outputfile", help="output csv file")
args = parser.parse_args()
filename = args.inputfile
output = args.outputfile
parameter.read_file(filename)

def my_toporder(g, scale):
    """ Return the list of `g` vertices at scale `scale` in topological order """
    axes = []
    map(axes.extend,(traversal.pre_order2(g,vid)
                          for vid in g.vertices(scale=scale)
                          if not g.parent(vid)))
    return axes

# read architecture file
def read_archi_data(fn):
    df = pd.read_csv(fn, sep = '\t', dtype = {'order': str})
    df['db'] = df['distance_from_base_(mm)'] * 1.e-3
    df['lr'] = df['lateral_root_length_(mm)'] * 1.e-3

    return df

def generate_g(seed = None, length_data = None, branching_variability = 0.25,
               delta = 2e-3, nude_length = 2e-3, primary_length = 0.13, segment_length = 1e-4, order_max = 4):
    """generate a MTG according to the input parameters
    Author: F. Bauget, based on routine writtent by C. Pradal, Y. Boursiac
    Date: 2019-12-10

    Parameters
    ==========
        - seed: the seed for the random generator in the markof chain
        - length_data: pandas dataframe columns names 'LR_length_mm', 'relative_distance_to_tip' sorted by 'relative_distance_to_tip'
        - branching_variability: probability of ramification at exact mean branching position
        - branching_delay: reference distance between successive branching axis
        - nude_length: length at root tip with no ramification
        - primary_length: primary root length
        - segment_length: length of the vertices, default 1.e-4
        - order_max: maximum lateral roots order

    Returns
    =======
        - g: MTG with the following properties set: edge_type, label, position
    """

    # nude length and branching delay in terms of number of vertices
    nb_nude_vertices = int(nude_length / segment_length)
    branching_delay = int(delta / segment_length)

    nb_vertices = int(primary_length / segment_length)

    length_max_secondary = length_data[0].LR_length_mm.max() * 1e-3  # in m

    # 'expo', True, False
    _uniform = 'expo'

    # Just use the same order1 law
    law_order1 = length_law(length_data[0], scale_x = primary_length / 100., scale = segment_length, uniform = _uniform)
    if EXPOVARIATE:
        law_order2 = length_law(length_data[1], scale_x = length_max_secondary / 100., scale = segment_length,
                                uniform = _uniform)
    else:
        law_order2 = length_law(length_data[1], scale_x = length_max_secondary / 100., scale = segment_length)

    g = markov.markov_binary_tree(
        nb_vertices = nb_vertices,
        branching_variability = branching_variability,
        branching_delay = branching_delay,
        length_law = [law_order1, law_order2] if not ONE_LAW else law_order1,
        nude_tip_length = nb_nude_vertices,
        order_max = order_max,
        seed = seed)
    return g

def length_law(pd, scale_x = 1 / 100., scale_y = 1., scale = 1e-4, uniform = True):
    """
    scale
    """
    x = pd.relative_distance_to_tip.tolist()
    y = pd.LR_length_mm.tolist()

    # size of the windows: 5%
    size = 5. * scale_x

    _length_law = histo_relative_law(x, y,
                                     size = size,
                                     scale_x = scale_x,
                                     scale_y = 1.e-3 * scale_y,
                                     scale = scale,
                                     plot = False,
                                     uniform = uniform)
    return _length_law

def ref_length_law(pd, scale_x = 1 / 100., scale_y = 1., scale = 1e-4, uniform = True):
    """
    scale
    """
    x = pd.relative_distance_to_tip.tolist()
    y = pd.LR_length_mm.tolist()

    # size of the windows: 5%
    size = 5. * scale_x

    _length_law = reference_relative_law(x, y,
                                         size = size,
                                         scale_x = scale_x,
                                         scale_y = 1.e-3 * scale_y)
    return _length_law

# to change the conductivities values by a factor to be able to do some
#    sensitivity studie
def radial(v = 92, acol = [], scale = 1):
    xr = acol[0]  # at this stage kr constant so the same x than Ka
    yr = [v * scale] * len(xr)
    return xr, yr

def axial(acol = [], scale = 1):
    x, y = acol
    y = [a * scale for a in y]

    return x, y

def my_seed():
    """ Define my own seed function to capture the seed value. """
    return int(long(_hexlify(_urandom(2500)), 16) % 100000000)

def root_creation(primary_length, seed = None, delta = 2.0e-3, nude_length = 2.0e-2, df = None):
    """
    creation of an mtg with properties like radius and vertex length set.

    The MTG is either generated or created from a data.
    The radius and vertex length properties are set.
    The following properties are computed: length, position, mylength, surface, volume, total length,
        primary root length, nb of intercepts

    :param:
        primary_length: primary root length for generated mtg
        seed:  seed for generated mtg, if None randomly generated
        delta: branching delay  for generated mtg
        nude_length: length from tip without lateral for generated mtg
        df: pandas DataFrame with the architecture data to be reconstructed
    :return:
        g: MTG with the different properties set or computed (see comments above),
        primary_length: primary root length (output for generated mtg)
        _length: total root length
        surface: total root surface
        intercepts: nb of intercepts at a given distance from base
        _seed: the seed used in the generator
        integral_diff: debug calculation to test generated lateral length law gap with the experimental one
    """
    if parameter.archi['read_architecture']:
        g = mtg_from_aqua_data(df, parameter.archi['segment_length'])
        _seed = None
    else:
        # if no seed just create one
        if seed is None:
            _seed = my_seed()
        else:
            _seed = seed

        length_data = parameter.archi['length_data']
        g = generate_g(_seed, length_data,
                       parameter.archi['branching_variability'], delta,
                       nude_length, primary_length, parameter.archi['segment_length'],
                       parameter.archi['order_max'])
    # F. Bauget 2020-03-18 for debug rsml import
    # g_c = rsml.rsml2mtg('/home/fabrice/Documents/hydroroot_FB/example/data/arabidopsis-simple.rsml')
    # g = my_continuous_to_discrete(g_c, segment_length = parameter.archi['segment_length'], resolution = 1e-4)
    # for rid in g.roots_iter(scale = 3):
    #     g.property('edge_type')[rid] = '+'
    # g.properties()['order'] = orders(g, scale = -1)
    # g = make_dicotomous_topo_mtg(magnitude = 16, segment_length = parameter.archi['segment_length'],link_length = 0.1)
    # g = make_herringbone_topo_mtg(magnitude = 16, segment_length = parameter.archi['segment_length'],link_length = 0.01)
    # F. Bauget 2020-03-18

    # compute radius property on MTG
    g = radius.ordered_radius(g, parameter.archi['ref_radius'], parameter.archi['order_decrease_factor'])

    # compute length property and parametrisation
    g = radius.compute_length(g, parameter.archi['segment_length'])
    g = radius.compute_relative_position(g)

    # Calculation of the distance from base of each vertex, used for cut and flow
    # Remark: this calculation is done in flux.segments_at_length; analysis.nb_roots but there is a concern with the
    # parameter dl which should be equal to vertex length but which is not pass
    _mylength = {}
    for v in traversal.pre_order2(g, 1):
        pid = g.parent(v)
        _mylength[v] = _mylength[pid] + parameter.archi['segment_length'] if pid else parameter.archi['segment_length']
    g.properties()['mylength'] = _mylength

    # _length is the total length of the RSA (sum of the length of all the segments)
    _length = g.nb_vertices(scale = 1) * parameter.archi['segment_length']
    g, surface = radius.compute_surface(g)
    g, volume = radius.compute_volume(g)

    # compute difference of length laws
    # integral_diff = 0.
    # if not parameter.archi['read_architecture']:
    #     X, Y = flux.ramification_length_law(g, root = 1, dl = parameter.archi['segment_length'])
    #     length_law_mtg = length.fit_law(X, Y, ext = 2)
    #     ref_law = ref_length_law(parameter.archi['length_data'][0], scale_x = 1. / 100.)
    #
    #     integral_diff = length.diff(length_law_mtg, ref_law)
    # else:
    #     integral_diff = None
    #     v_base = g.component_roots_at_scale_iter(g.root, scale = g.max_scale()).next()
    #     primary_length = g.property('position')[v_base]

    # Compute the intercepts
    intercepts = intercept(g, sorted(parameter.output['intercepts']))
    # ## if intercepts are relative to primary root
    # new_int = []
    # for x in parameter.output['intercepts']:
    #     new_int.append(x * primary_length)
    # intercepts = intercept(g, sorted(new_int))

    return g, primary_length, _length, surface, intercepts, _seed #, integral_diff

def hydro_calculation(g, axfold = 1., radfold = 1., axial_data = None, k_radial = None, cut_and_flow = False):
    if axial_data is None: axial_data = parameter.hydro['axial_conductance_data']
    if k_radial is None: k_radial = parameter.hydro['k0']
    # compute axial & radial
    Kexp_axial_data = axial(axial_data, axfold)
    k_radial_data = radial(k_radial, axial_data, radfold)

    # compute local jv and psi, global Jv, Keq
    g, Keq, Jv_global = hydroroot_flow(g,
                                       segment_length = parameter.archi['segment_length'],
                                       k0 = k_radial,
                                       Jv = parameter.exp['Jv'],
                                       psi_e = parameter.exp['psi_e'],
                                       psi_base = parameter.exp['psi_base'],
                                       axial_conductivity_data = Kexp_axial_data,
                                       radial_conductivity_data = k_radial_data)

    return g, Keq, Jv_global

if __name__ == '__main__':
    j_relat = {}
    seg_at_position = [1, 20, 40, 65, 100, 120, 125, 130, 135, 140, 145, 150, 155]  # distance from tip

    dseeds = pd.read_csv('/home/fabrice/Documents/Arabidopsis/Papier/subset_generated-roots-20-10-07_PR_016.csv')
    _seeds = list(dseeds['seed'])
    _delta = list(dseeds['delta'])
    _primary_length = list(dseeds['primary_length'])
    _nude_length = list(dseeds['nude_length'])
    
    # predict the number of simulation run
    nb_steps = len(parameter.output['axfold']) * len(_seeds)
    print 'Simulation runs: ', nb_steps
    print '#############################'

    _columns = []
    _columns.append('ax')
    j_relat['ax'] = []
    for i in seg_at_position:
        _columns.append(str(i) + ' mm')
        j_relat[str(i) + ' mm'] = []
    _columns.append('Jv')
    j_relat['Jv'] = []
    count2 = 0


    for seed in _seeds:
        primary_length = _primary_length[count2]
        delta = _delta[count2]
        nude_length = _nude_length[count2]
        count2 += 1

        g, primary_length, _length, surface, intercepts, _seed = root_creation(
            primary_length = primary_length,
            seed = seed,
            delta = delta,
            nude_length = nude_length)

        vertices_at_length = []
        v_base = g.component_roots_at_scale_iter(g.root, scale = g.max_scale()).next()
        n_max = max(axis(g,v_base))

        for l in seg_at_position:
            ## only on PR
            vids = int(n_max-l*1.0e-3/parameter.archi['segment_length'])
            vertices_at_length.append([vids])

        j1 = {}
        for axfold in parameter.output['axfold']:
            for radfold in parameter.output['radfold']:
                avg_fold = axfold # the factor on winch the relative j is calculated
                other_fold = radfold # the other
                if avg_fold == 1: j1[other_fold] = []

                g, Keq, Jv = hydro_calculation(g, axfold = axfold, radfold = radfold)

                if avg_fold == 1:
                    g.add_property('j_relat')
                    g_1 = g.copy()
                else:
                    for v in g:
                        if v>0: g.property('j_relat')[v] = g.property('J_out')[v]/g_1.property('J_out')[v]

                c = 0
                for l in seg_at_position:
                    c += 1
                    jtot = 0.0
                    n = len(vertices_at_length[c-1])
                    for v in vertices_at_length[c-1]:
                        # remark: when done on the PR there is only 1 vertex
                        jtot += g.property('J_out')[v]

                    if avg_fold == 1:
                        j1[other_fold].append(jtot)
                        j_relat[str(l) + ' mm'].append(l*1e-3)
                    else:
                        j_relat[str(l) + ' mm'].append(jtot/j1[other_fold][c-1])

                if avg_fold == 1:
                    j1[other_fold].append(Jv)
                    j_relat['Jv'].append(primary_length)
                else:
                    j_relat['Jv'].append(Jv/j1[other_fold][c])

                j_relat['ax'].append(axfold)
        nb_steps -= len(parameter.output['axfold'])
        print 'nb of runs left: ', nb_steps

    dj2 = pd.DataFrame(j_relat, columns = _columns)
    dj2.to_csv("j_relat.csv", index = False, header = False)
