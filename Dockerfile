FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    curl \
    git \
    wget \
    tar\
    unzip\
    make \
    python3 \
    python3-dev\
    pkg-config \
    libffi-dev \
    libgmp-dev \
    zlib1g-dev
    
# Copy everything to the working directory
WORKDIR /vcml-pydrofoil
COPY . .

#Install PyPy for Pydrofoil
# Download the tar with wget, unpacks it with tar -xjf and moves the pypy folder to /opt/
RUN wget https://downloads.python.org/pypy/pypy3.11-v7.3.21-linux64.tar.bz2 && \
    tar -xjf pypy3.11-v7.3.21-linux64.tar.bz2 && \
    mv pypy3.11-v7.3.21-linux64 /opt/pypy && \
    ln -s /opt/pypy/bin/pypy3 /usr/local/bin/pypy3 && \
    rm pypy3.11-v7.3.21-linux64.tar.bz2

ENV PATH="/opt/pypy/bin:$PATH"
ENV PYTHONPATH="/vcml-pydrofoil"

#Unzip the Pydrofoil-PyPy plugin from downloaded artifact 
# RUN unzip artifact.zip -d ./artifact
# RUN mkdir -p ./pypy-pydrofoil-scripting-experimental && \
#     tar -xjf ./artifact/pypy-pydrofoil-scripting-experimental.tar.bz2 \
#        -C ./pypy-pydrofoil-scripting-experimental --strip-components=1

RUN chmod a+x build_sim.sh
RUN ./build_sim.sh

ENV LD_LIBRARY_PATH=/vcml-pydrofoil/pypy-pydrofoil-scripting-experimental/bin:/vcml-pydrofoil:/vcml-pydrofoil/build:/vcml-pydrofoil/sysc_vp:${LD_LIBRARY_PATH:-}

RUN chmod a+x launch.sh

# RUN inherits host's umask, on alma this results in "no permission" later on (podman)
RUN chmod -R a+rX /vcml-pydrofoil /opt/pypy

# We're going to be using the absolute path, since the path starts with the "/"
ENTRYPOINT ["/vcml-pydrofoil/launch.sh"]
CMD ["/vcml-pydrofoil/benchmark/riscv64_ex.cfg"]
