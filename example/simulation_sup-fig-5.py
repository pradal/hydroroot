###############################################################################
# Date: 2021-06-18
# F. Bauget
#   Use of HydroRoot to calcul local relative fluxes on some sensibility analysis 
#   on the axial and radial conductivity using  a set of known architectures generated-roots-20-10-07.csv
#   Sensibility analysis on the factor axfold on axial data and radfold on radial k given in the parameter yaml file are used
###############################################################################

######
# Imports

# VERSION = 2

from random import _hexlify, _urandom

from pylab import cm
import numpy as np
import pandas as pd
import argparse
import sys
import time
import tempfile, os

from matplotlib.colors import Normalize

import openalea.plantgl.all as pgl
from openalea.mtg import turtle as turt
from openalea.mtg.plantframe import color
from openalea.mtg import traversal
from openalea.mtg.algo import axis
from IPython.display import Image, display

from hydroroot import radius, markov
from hydroroot.law import histo_relative_law
from hydroroot.generator.measured_root import mtg_from_aqua_data
from hydroroot.analysis import intercept
from hydroroot.main import hydroroot_flow
from hydroroot.init_parameter import Parameters
from hydroroot.display import get_root_visitor

ONE_LAW = False
EXPOVARIATE = True
results = {}

start_time = time.time()

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

# read architecture file
def read_archi_data(fn):
    """
    Read a csv (tab separated) file with the architecture in the following format
        |'distance_from_base_(mm)' | 'lateral_root_length_(mm)' | order |
        |float | float | string|
        order = 1 for laterals of 1st order ob the primary
        order = n-m for the lateral number m on the lateral number n of 1st order
        order = n-m-o for the lateral number o of the previous one
        etc.
        Each branch finish with a nude part, i.e. a distance from base (the tip value) and a zero length

    :param fn: string - the architecture filename in csv format

    :return: DataFrame
    """
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
    Creation of the function giving the lateral length according to its position on the parent branch

    :param pd: DataFrame - DataFrame with the laterals length law
    :param scale_x: float (0.01) - x scale by default transform x in % to real value
    :param scale_y: float (1.0) - any possible scale factor on y
    :param scale: float (1e-4) - the segment length (m)
    :param uniform: boolean or string (False) - if False use randomly an exact data point, True use a uniform distribution
            between the minimum and the maximum of the data LR_length_mm, if 'expo', use an expovariate law
    :return: a function giving the lateral length according to its position
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

    # Compute the intercepts
    intercepts = intercept(g, sorted(parameter.output['intercepts']))

    return g, primary_length, _length, surface, intercepts, _seed

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

def plot(g1, has_radius=True, r_base=1.e-4, r_tip=5e-5, prop_cmap='radius', cmap='jet',lognorm=None,
         prune=None, name=None):
    """
    Display the architecture in plantGL Viewer with roots colors according to the property chosen
    :param g: MTG()
    :param has_radius: Boolean (False) - True use the radius property values, calculate them otehrwise according to r_base and r_tip
    :param r_base: float (1e-4) - if has_radius is False, the radius at the base of a root whatever its order (mm)
    :param r_tip: float (5e-5) - if has_radius is False, the radius at the tip of a root whatever its order (mm)
    :param prop_cmap: string ('radius') - the property name used for the color map
    :param cmap: string ('jet') - the name of the matplotlib colormap to use
    :param lognorm: Boolean (False) - True: log-normalised, normalised otherwise
    :param prune: float (None) - distance from the base of the primary after which the root is not displayed
    :param name: string (None) - if not None, the name of the saved file
    :return:
    """
    g = g1.copy() # because we may change the radius if we want
    visitor = get_root_visitor(prune=prune)

    # changing radius just for display
    r_base, r_tip = float(r_base), float(r_tip)
    if not has_radius:
        radius.discont_radius(g,r_base=r_base, r_tip=r_tip)

    turtle = turt.PglTurtle()
    turtle.down(180)
    scene = turt.TurtleFrame(g, visitor=visitor, turtle=turtle, gc=False)

    # Compute color from radius
    if type(lognorm) is bool:
        color.colormap(g,prop_cmap, cmap=cmap, lognorm=lognorm)
    else:
        my_colormap_not_normed(g,prop_cmap, cmap=cmap)

    shapes = dict( (sh.getId(),sh) for sh in scene)

    colors = g.property('color')
    for vid in colors:
        if vid in shapes:
            shapes[vid].appearance = pgl.Material(colors[vid])
    scene = pgl.Scene(shapes.values())

    pgl.Viewer.display(scene)
    if name is not None:
            pgl.Viewer.frameGL.saveImage(name)

def my_colormap_not_normed(g, property_name, cmap='jet'):
    # F. Bauget 2020-04-01 : not normed colormap
    prop = g.property(property_name)
    keys = prop.keys()
    values = np.array(prop.values())
    _cmap = cm.get_cmap(cmap)

    colors = (_cmap(values)[:,0:3])*255
    colors = np.array(colors,dtype=np.int).tolist()

    g.properties()['color'] = dict(zip(keys,colors))

def my_plot_with_bar(g, prop, lognorm = None):
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    import numpy as np

    values = np.array(g.property(prop).values())
    plot(g, prop_cmap = prop, lognorm = lognorm)

    if type(lognorm) is bool:
        vmin = values.vmin()
        vmax = values.max()
    else:
        vmin = 0.0
        vmax = 1.0

    fig, ax = plt.subplots(figsize = (6, 1))
    fig.subplots_adjust(bottom = 0.5)
    cmap = mpl.cm.jet
    norm = mpl.colors.Normalize(vmin = vmin, vmax = vmax)
    cb1 = mpl.colorbar.ColorbarBase(ax, cmap = cmap, norm = norm, orientation = 'horizontal')
    cb1.set_label(prop)
    fig.show()

if __name__ == '__main__':
    j_relat = {}
    seg_at_position = [1, 20, 40, 65, 100, 120, 125, 130, 135, 140, 145, 150, 155]  # distance from tip

    # dseeds = pd.read_csv('data/subset_generated-roots-20-10-07_PR_016.csv')
    dseeds = pd.read_csv('data/short_subset_generated-roots-20-10-07_PR_016.csv')
    # dseeds = pd.read_csv('data/test.csv')
    _seeds = list(dseeds['seed'])
    _delta = list(dseeds['delta'])
    _primary_length = list(dseeds['primary_length'])
    _nude_length = list(dseeds['nude_length'])
    
    # predict the number of simulation run
    nb_steps = len(parameter.output['axfold']) * len(_seeds)
    nb_steps2=nb_steps
    print 'Simulation runs: ', nb_steps
    print '#############################'

    _columns = []
    _columns.append('ax')
    j_relat['ax'] = []
    for i in seg_at_position:
        _columns.append(str(i) + ' mm')
        j_relat[str(i) + ' mm'] = []
    _columns.append('base')
    j_relat['base'] = []

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

        g_ax = {}
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
                    for v in g.vertices_iter(scale = g.max_scale()):
                        g.property('j_relat')[v] = g.property('J_out')[v]/g_1.property('J_out')[v]

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
                        j_relat[str(l) + ' mm'].append(1.0)
                    else:
                        j_relat[str(l) + ' mm'].append(jtot/j1[other_fold][c-1])

                if avg_fold == 1:
                    j1[other_fold].append(Jv)
                    j_relat['base'].append(1.0)
                else:
                    j_relat['base'].append(Jv/j1[other_fold][c])

                j_relat['ax'].append(axfold)

                nb_steps2 -= 1
                sys.stdout.write('\r')
                sys.stdout.write('{:0.4}'.format(100.0 - float(nb_steps2)/float(nb_steps)*100) + ' %')
                sys.stdout.flush()

            if (seed == 37430610) & (round(axfold,2) in [0.05,0.25,0.5,0.75]):
                print ' ax = ', axfold
                # g has radius, here we set fictive radii just for visual comfort
                alpha = 0.2  # radius in millimeter identical for all orders
                plot(g, has_radius = False, r_base = alpha * 1.e-3, r_tip = alpha * 9.9e-4, prop_cmap = 'j_relat', lognorm = None)
                pgl.Viewer.widgetGeometry.setSize(450, 600)  # set the picture size in px
                fn = tempfile.mktemp(suffix = '.png')
                pgl.Viewer.saveSnapshot(fn)
                pgl.Viewer.stop()
                img = Image(fn)
                os.unlink(fn)
                display(img)


    dj2 = pd.DataFrame(j_relat, columns = _columns)
    if output is not None: dj2.to_csv(output, index = False)

    ax = {}
    for s in ['1 mm', '65 mm', '130 mm']:
        ax[s] = dj2.plot.scatter('ax', s, color = 'orange', edgecolors = 'orange', label = s + ' to tip')
        dj2.plot.scatter('ax', 'base', ax = ax[s], color = 'blue', edgecolors = 'blue', label = 'base')
        ax[s].set_ylabel('Normalize local flow (J)')
        ax[s].legend(loc = 'upper left')
        ax[s].set_xlim((0, 1))
        ax[s].set_ylim((0, 1))

    print 'running time is ', time.time() - start_time