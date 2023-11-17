[![tests](https://github.com/madebydaniz/ddev-orthanc/actions/workflows/tests.yml/badge.svg)](https://github.com/madebydaniz/ddev-orthanc/actions/workflows/tests.yml) ![project is maintained](https://img.shields.io/maintenance/yes/2024.svg)

# ddev-orthanc <!-- omit in toc -->

* [What is ddev-orthanc?](#what-is-ddev-orthanc)
* [Installation](#installation)
* [Explanation](#explanation)

## What is ddev-orthanc?
This repository allows you to quickly install Orthanc into a [DDEV](https://ddev.readthedocs.io) project using just `ddev get ddev/ddev-orthanc`.

Orthanc aims at providing a simple, yet powerful standalone DICOM server. It is designed to improve the DICOM flows in hospitals and to support research about the automated analysis of medical images. Orthanc lets its users focus on the content of the DICOM files, hiding the complexity of the DICOM format and of the DICOM protocol.

Orthanc can turn any computer running Windows, Linux or OS X into a DICOM store (in other words, a mini-PACS system). Its architecture is lightweight and standalone, meaning that no complex database administration is required, nor the installation of third-party dependencies.

## Installation

1. `ddev get ddev/ddev-orthanc`
2. `ddev restart`

## Explanation

This Orthanc recipe for [DDEV](https://ddev.readthedocs.io) installs a [`.ddev/docker-compose.orthanc.yaml`](docker-compose.orthanc.yaml) using the [`osimis/orthanc`](https://hub.docker.com/r/osimis/orthanc/) Docker image.

## Accessing Orthanc and DICOM Services

**Orthanc URL**

The Orthanc server can be accessed via the following URL:
```bash
Orthanc URL = http://{PROJECT_URL}:8042
```

**DICOM URL**

For DICOM communication, use this URL:

```bash
DICOM URL = {PROJECT_URL}:4242
```

**Testing DICOM Communication**

To test the communication with the DICOM server, you can use the `dcmsend` command.
This example demonstrates sending a DICOM directory:

```bash
echoscu {PROJECT_URL} 4242 -aec AETITLE -ll info
dcmsend {PROJECT_URL} 4242 DIRECTORY +sd +ma --aetitle AETITLE --call AETITLE
```

Replace `{PROJECT_URL}` with your actual project URL, and `DIRECTORY` with the path to the DICOM files you want to send.

**Contributed and maintained by [@madebydaniz](https://github.com/madebydaniz)**
