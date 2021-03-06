import sklearn.metrics, sklearn.cross_validation
import statsmodels.formula.api as sm
import simtk.unit as u
import polarizability
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd

sns.set_palette("bright")
sns.set_style("whitegrid")
sns.set(font_scale=1.2)


expt = pd.read_csv("./tables/data_with_metadata.csv")
expt["temperature"] = expt["Temperature, K"]


pred = pd.read_csv("./tables/predictions.csv")
pred["polcorr"] = pd.Series(dict((cas, polarizability.dielectric_correction_from_formula(formula, density * u.grams / u.milliliter)) for cas, (formula, density) in pred[["formula", "density"]].iterrows()))
pred["corrected_dielectric"] = pred["polcorr"] + pred["dielectric"]

expt = expt.set_index(["cas", "temperature"])  # Can't do this because of duplicates  # Should be fixed now, probably due to the CAS / name duplication issue found by Julie.
#expt = expt.groupby(["cas", "temperature"]).mean()  # Fix a couple of duplicates, not sure how they got there.
pred = pred.set_index(["cas", "temperature"])

pred["expt_density"] = expt["Mass density, kg/m3"]
pred["expt_dielectric"] = expt["Relative permittivity at zero frequency"]
#pred["expt_density_std"] = expt["Mass density, kg/m3_std"]
pred["expt_density_std"] = expt["Mass density, kg/m3_uncertainty_bestguess"]
#pred["expt_dielectric_std"] = expt["Relative permittivity at zero frequency_std"]
pred["expt_dielectric_std"] = expt["Relative permittivity at zero frequency_uncertainty_bestguess"]



yerr = pred["expt_dielectric_std"].replace(np.nan, 0.0)
xerr = pred["dielectric_sigma"].replace(np.nan, 0.0)

plt.figure()

plt.xlabel("Predicted (GAFF)")
plt.ylabel("Experiment (ThermoML)")
title("Static Dielectric Constant")

MIN = 1
MAX = 300

plt.plot([MIN, MAX], [MIN, MAX], 'k')  # Guide


x, y = pred["dielectric"], pred["expt_dielectric"]
ols_model = sm.OLS(y, x)
ols_results = ols_model.fit()
r2 = ols_results.rsquared
plt.errorbar(x, y, xerr=xerr, yerr=yerr, fmt='.', label="GAFF")
xscale('log')
yscale('log')

xlim((MIN, MAX))
ylim((MIN, MAX))
plt.legend(loc=0)
plt.gca().set_aspect('equal', adjustable='box')
plt.draw()
plt.savefig("./manuscript/figures/dielectrics_thermoml_nocorr_logscale.pdf", bbox_inches="tight")


x, y = pred["corrected_dielectric"], pred["expt_dielectric"]
ols_model = sm.OLS(y, x)
ols_results = ols_model.fit()
r2 = ols_results.rsquared
plt.errorbar(x, y, xerr=xerr, yerr=yerr, fmt='.', label="Corrected")
xscale('log')
yscale('log')

xlim((MIN, MAX))
ylim((MIN, MAX))
plt.legend(loc=0)
plt.gca().set_aspect('equal', adjustable='box')
plt.draw()
plt.savefig("./manuscript/figures/dielectrics_thermoml_logscale.pdf", bbox_inches="tight")
