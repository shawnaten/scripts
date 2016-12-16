FROM ubuntu:trusty

RUN apt-get update && apt-get install -y \
  build-essential \
  python3 \
  vim

RUN adduser --system grader --shell /bin/bash

COPY grade.py /usr/local/bin/grade
RUN chmod a+rwx /usr/local/bin/grade

WORKDIR /home/grader
USER grader
