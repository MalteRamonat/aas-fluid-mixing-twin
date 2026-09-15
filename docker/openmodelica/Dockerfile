# OpenModelica with the Modelica Standard Library the model declares (uses(Modelica 4.0.0)),
# installed at build time so the image is self-contained. Used for two things:
#   * scripts/export_fmu.py   — one-off FMU export (omc script)
#   * compose profile `om`    — om_worker.py, recompiling and simulating the .mo on demand
#
# OMPython starts omc as a server, which omc refuses to do as root; hence the `modva` user.
FROM openmodelica/openmodelica:v1.22.1-ompython

# cmake: the FMU export's build step needs it and the base image does not ship it.
RUN apt-get update && apt-get install -y --no-install-recommends cmake     && rm -rf /var/lib/apt/lists/*     && useradd --create-home --uid 1000 modva
USER modva
ENV HOME=/home/modva USER=modva

RUN printf 'updatePackageIndex(); getErrorString();\n\
installPackage(Modelica, "4.0.0", exactMatch=true); getErrorString();\n\
loadModel(Modelica, {"4.0.0"}); getErrorString();\n\
print("MSL " + getVersion(Modelica) + "\n");\n' > /tmp/install_msl.mos \
    && omc /tmp/install_msl.mos && rm /tmp/install_msl.mos

COPY --chown=modva docker/openmodelica/om_worker.py /opt/om_worker.py

WORKDIR /work
EXPOSE 8010
CMD ["python3", "/opt/om_worker.py"]
