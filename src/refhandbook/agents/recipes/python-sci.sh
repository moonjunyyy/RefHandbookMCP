# The scientific stack, into the parent layer's Python (its site-packages is under /opt/python).
set -eu
/usr/local/bin/uv pip install --python /usr/local/bin/python3 --system --break-system-packages \
  numpy scipy sympy mpmath pandas matplotlib networkx scikit-learn statsmodels pillow pyyaml tqdm h5py \
  numba ipython
/usr/local/bin/python3 -c "import numpy, scipy, sympy, pandas, matplotlib, sklearn; print('ok', numpy.__version__)"
