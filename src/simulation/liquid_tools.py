import numpy as np
import os
import itertools
import mdtraj as md

from simtk.openmm import app
import simtk.openmm as mm
from simtk import unit as u

from density_simulation_parameters import *
import gaff2xml

from pymbar import timeseries as ts
import pandas as pd

def make_path(filename):
    try:
        path = os.path.split(filename)[0]
        os.makedirs(path)
    except OSError:
        pass


class AmberMixtureSystem(object):
    """A pipeline for simulating liquid mixtures using amber parameter files.
    
    Parameters
    ----------
    cas_strings : list(str)
        CAS strings for each component of the mixture
    n_monomers: list(int)
        Number of each type of molecule
    temperature : simtk.unit
        Temperature to run simulation.
    """

    def __init__(self, cas_strings, n_monomers, temperature):

        self.cas_strings = cas_strings
        self.n_monomers = n_monomers
        self.temperature = temperature

        identifier = list(itertools.chain(cas_strings, [str(n) for n in n_monomers], [str(temperature).split(' ')[0]]))
        self.identifier = '_'.join(identifier)        
        
        self.monomer_pdb_filenames = [DATA_PATH + "monomers/" + string + ".pdb" for string in self.cas_strings]
        self.box_pdb_filename = DATA_PATH + "packmol_boxes/" + self.identifier + ".pdb"
        
        self.inpcrd_filename = DATA_PATH + "tleap/" + self.identifier + ".inpcrd"
        self.prmtop_filename = DATA_PATH + "tleap/" + self.identifier + ".prmtop"
        
        self.equil_dcd_filename = DATA_PATH + "equil/" + self.identifier + "_equil.dcd"
        self.equil_pdb_filename = DATA_PATH + "equil/" + self.identifier + "_equil.pdb"
        
        self.production_dcd_filename = DATA_PATH + "production/" + self.identifier + "_production.dcd"
        self.production_pdb_filename = DATA_PATH + "production/" + self.identifier + "_production.pdb"
        self.production_data_filename = DATA_PATH + "production/" + self.identifier + "_production.csv"
        
        self.gaff_mol2_filenames = [DATA_PATH + "monomers/" + string + ".mol2" for string in self.cas_strings]
        self.frcmod_filenames = [DATA_PATH + "monomers/" + string + ".frcmod" for string in self.cas_strings]
        
        make_path(DATA_PATH + 'monomers/')
        make_path(DATA_PATH + 'packmol_boxes/')
        make_path(DATA_PATH + 'tleap/')
        
        make_path(DATA_PATH + 'equil/')
        make_path(self.equil_pdb_filename)        
        
        make_path(DATA_PATH + 'production/')
        make_path(self.production_dcd_filename)        

    @property
    def smiles_strings(self):
        self._smiles_strings = []
        for mlc in self.cas_strings:
            self._smiles_strings.append(gaff2xml.cirpy.resolve(mlc, 'smiles'))
        
        return self._smiles_strings

    def run(self):
        self.build_monomers()
        self.build_boxes()
        self.equilibrate()
        self.production()

    def build_monomers(self):
        """Generate GAFF mol2 and frcmod files for each chemical."""
        for k, smiles_string in enumerate(self.smiles_strings):
            mol2_filename = self.gaff_mol2_filenames[k]
            frcmod_filename = self.frcmod_filenames[k]
            if not (os.path.exists(mol2_filename) and os.path.exists(frcmod_filename)):
                gaff2xml.openeye.smiles_to_antechamber(smiles_string, mol2_filename, frcmod_filename)


    def build_boxes(self):
        """Build an initial box with packmol and use it to generate AMBER files."""
        if not os.path.exists(self.box_pdb_filename):
            packed_trj = gaff2xml.packmol.pack_box([md.load(mol2) for mol2 in self.gaff_mol2_filenames], self.n_monomers)
            packed_trj.save(self.box_pdb_filename)

        if not (os.path.exists(self.inpcrd_filename) and os.path.exists(self.prmtop_filename)):
            tleap_cmd = gaff2xml.amber.build_mixture_prmtop(self.gaff_mol2_filenames, self.frcmod_filenames, self.box_pdb_filename, self.prmtop_filename, self.inpcrd_filename)


    def equilibrate(self):
        
        if os.path.exists(self.equil_pdb_filename):
            return

        prmtop = app.AmberPrmtopFile(self.prmtop_filename)
        inpcrd = app.AmberInpcrdFile(self.inpcrd_filename)

        system = prmtop.createSystem(nonbondedMethod=app.PME, nonbondedCutoff=CUTOFF, constraints=app.HBonds)
        integrator = mm.LangevinIntegrator(self.temperature, EQUIL_FRICTION, EQUIL_TIMESTEP)
        system.addForce(mm.MonteCarloBarostat(PRESSURE, self.temperature, BAROSTAT_FREQUENCY))

        simulation = app.Simulation(prmtop.topology, system, integrator)
        simulation.context.setPositions(inpcrd.positions)

        state = simulation.context.getState(getEnergy=True)
        print(state.getPotentialEnergy())
        
        print('Minimizing.')
        simulation.minimizeEnergy()
        
        state = simulation.context.getState(getEnergy=True)
        print(state.getPotentialEnergy())

        simulation.context.setVelocitiesToTemperature(self.temperature)
        print('Equilibrating.')

        simulation.reporters.append(app.DCDReporter(self.equil_dcd_filename, OUTPUT_FREQUENCY_EQUIL))
        simulation.step(N_EQUIL_STEPS)

        # Re-write a better PDB with correct box sizes.
        traj = md.load(self.equil_dcd_filename, top=self.prmtop_filename)[-1]
        traj.save(self.equil_pdb_filename)

    def production(self):  

        if os.path.exists(self.production_dcd_filename) and os.path.exists(self.production_data_filename):
            return

        prmtop = app.AmberPrmtopFile(self.prmtop_filename)
        pdb = app.PDBFile(self.equil_pdb_filename)

        system = prmtop.createSystem(nonbondedMethod=app.PME, nonbondedCutoff=CUTOFF, constraints=app.HBonds)

        integrator = mm.LangevinIntegrator(self.temperature, FRICTION, TIMESTEP)
        system.addForce(mm.MonteCarloBarostat(PRESSURE, self.temperature, BAROSTAT_FREQUENCY))

        simulation = app.Simulation(prmtop.topology, system, integrator)
        
        simulation.context.setPositions(pdb.positions)
        simulation.context.setPeriodicBoxVectors(*pdb.topology.getPeriodicBoxVectors())
        simulation.context.setVelocitiesToTemperature(self.temperature)
        
        print('Production.')
        
        simulation.reporters.append(app.DCDReporter(self.production_dcd_filename, OUTPUT_FREQUENCY))
        simulation.reporters.append(app.StateDataReporter(self.production_data_filename, OUTPUT_DATA_FREQUENCY, step=True, potentialEnergy=True, temperature=True, density=True))

        converged = False
        while not converged:
            simulation.step(N_STEPS)
            d = pd.read_csv(self.production_data_filename, names=["step", "U", "Temperature", "Density"], skiprows=1)
            density_ts = np.array(d.Density)
            [t0, g, Neff] = ts.detectEquilibration(density_ts, nskip=1000)
            density_ts = density_ts[t0:]
            density_mean_stderr = density_ts.std() / np.sqrt(Neff)
            if density_mean_stderr < STD_ERROR_TOLERANCE:
                converged = True
