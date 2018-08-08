# Faucet for NEP-5 tokens on NEO testnet - Dockerfile

FROM ubuntu:18.04

# gets rid of unnecessary warning messages
ARG DEBIAN_FRONTEND=noninteractive
# sets the timezone
ARG TZ="America/New_York"
#RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install system dependencies. always should be done in one line
# https://docs.docker.com/engine/userguide/eng-image/dockerfile_best-practices/#run
RUN apt-get update && apt-get install -yq \
    apt-utils \
    curl \
    wget \
    unzip \
    tar \
    screen \
    expect \
    git-core \
    vim \
    man \
    python3.6 \
    python3.6-dev \
    python3.6-venv \
    python3-pip \
    libleveldb-dev \
    libssl-dev \
    g++

# APT cleanup to reduce image size
# install nose because docker likes to break if you don't
# Create app directory, .aws directory, and Chains directories
RUN rm -rf /var/lib/apt/lists/* && \
    pip3 install nose==1.3.7 && \
    mkdir -p /app/ && \
    mkdir -p ~/.neopython/Chains && \
    mkdir -p ~/.aws

# copy app files from host to container
COPY ./app /app/

# set the working directory (seems not to work properly when only setting this in docker-compose)
WORKDIR /app/

# make np-setup executable
# move aws config and credentials to user's home directory ( '~/' is '/root' for docker ubuntu images)
# install app requirements
RUN cd /app/ && \
    mkdir /app/logs/ && \
    chmod +x /app/config/np-setup.exp && \
    mv /app/config/.aws/* ~/.aws/ && \
    pip3 install -r requirements.txt

# port to access the faucet web app
#EXPOSE 8080

# Run app when the container launches
CMD ["python3", "faucet.py"]
