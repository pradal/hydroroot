###############################################################################
#
# Authors: F. Bauget
# Date : 2021-06-10
#
# Test import-export rsml
###############################################################################

import glob
import rsml
import argparse
import sys

from openalea.mtg import MTG, traversal
from openalea.plantgl.all import Viewer

from hydroroot import radius
from hydroroot.main import hydroroot_flow
from hydroroot.init_parameter import Parameters  # import work in progress for reading init file
from hydroroot.hydro_io import export_mtg_to_rsml, import_rsml_to_discrete_mtg
from hydroroot.display import plot as mtg_scene

parameter = Parameters()

parser = argparse.ArgumentParser()
parser.add_argument("inputfile", help="yaml input file")
parser.add_argument("-op", "--optimize", help="optimize k value", action="store_true")
args = parser.parse_args()
filename = args.inputfile
Flag_Optim = args.optimize
if Flag_Optim is None: Flag_Optim = False
parameter.read_file(filename)

def radial(v = 92, acol = [], scale = 1):
    xr = acol[0]  # at this stage kr constant so the same x than Ka
    yr = [v * scale] * len(xr)

    return xr, yr

def axial(acol = [], scale = 1):
    x, y = acol
    y = [a * scale for a in y]

    return x, y

def root_creation(g):
    """
    Set MTG properties and perform some gemetrical calculation
    
    The vertex radius properties is set.
    The following properties are computed: length, position, mylength, surface, volume, total length,
        primary root length

    :param:
        - `g` (MTG)
        
    :return:
        `g`: MTG with the different properties set or computed (see comments above),
        `primary_length`: primary root length (m)
        `_length`: total root length (m)
        `surface`: total root surface (m^2)
    """

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


    v_base = g.component_roots_at_scale_iter(g.root, scale = g.max_scale()).next()
    primary_length = g.property('position')[v_base]

    return g, primary_length, _length, surface

def hydro_calculation(g, axfold = 1., radfold = 1., axial_data = None, k_radial = None):
    if axial_data is None: axial_data = parameter.hydro['axial_conductance_data']
    if k_radial is None: k_radial = parameter.hydro['k0']
    # compute axial & radial
    Kexp_axial_data = axial(axial_data, axfold)
    k_radial_data = radial(k_radial, axial_data, radfold)

    # compute local jv and psi, global Jv, Keq
    g, Keq, Jv = hydroroot_flow(g, segment_length = parameter.archi['segment_length'],
                                   k0 = k_radial,
                                   Jv = parameter.exp['Jv'],
                                   psi_e = parameter.exp['psi_e'],
                                   psi_base = parameter.exp['psi_base'],
                                   axial_conductivity_data = Kexp_axial_data,
                                   radial_conductivity_data = k_radial_data)

    return g, Keq, Jv

def plot(g, name=None, **kwds):
    Viewer.display(mtg_scene(g, **kwds))
    if name is not None:
            Viewer.frameGL.saveImage(name)

if __name__ == '__main__':
    axfold = parameter.output['axfold'][0]
    radfold = parameter.output['radfold'][0]

    rsml_units_to_metre = {}
    rsml_units_to_metre['m'] = 1.0
    rsml_units_to_metre['cm'] = 1.0e-2
    rsml_units_to_metre['mm'] = 1.0e-3
    rsml_units_to_metre['um'] = 1.0e-6
    rsml_units_to_metre['nm'] = 1.0e-9

    filename = []
    for f in parameter.archi['input_file']:
        filename = filename + (glob.glob(parameter.archi['input_dir'] + f))

    # import rsml
    g_c = rsml.rsml2mtg(filename[0])
    resolution = g_c.graph_properties()['metadata']['resolution']
    unit = g_c.graph_properties()['metadata']['unit']

    if unit not in rsml_units_to_metre.keys():
        sys.exit('wrong unit in rsml file, unit must be one of the following: m, cm, mm, um, nm.')

    resolution *= rsml_units_to_metre[unit] # rsml file unit to meter

    g = import_rsml_to_discrete_mtg(g_c, segment_length = parameter.archi['segment_length'], resolution = resolution)

    # calculation of g properties: radius, mylength, etc.
    g, primary_length, _length, surface = root_creation(g)

    # flux calculation
    g, Keq, Jv = hydro_calculation(g, axfold = axfold, radfold = radfold)

    print 'water flux from rsml file is ', Jv, ' uL/s'

    export_mtg_to_rsml(g, "test_rsml_io.rsml", segment_length = parameter.archi['segment_length'])
    g_c = rsml.rsml2mtg("test_rsml_io.rsml")
    resolution = g_c.graph_properties()['metadata']['resolution']
    unit = g_c.graph_properties()['metadata']['unit']
    resolution *= rsml_units_to_metre[unit] # rsml file unit to meter
    g2 = import_rsml_to_discrete_mtg(g_c, segment_length = parameter.archi['segment_length'], resolution = resolution)
    g2, primary_length2, _length2, surface2 = root_creation(g2)
    g2, Keq2, Jv2 = hydro_calculation(g2, axfold = axfold, radfold = radfold)

    print 'water flux from exported-imported to rsml MTG is ', Jv, ' uL/s'
    #
    print 'difference in: primary_length, _length, surface, Keq, Jv are:', primary_length-primary_length2, _length-_length2, surface-surface2, Keq-Keq2, Jv-Jv2


