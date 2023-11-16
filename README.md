[![tests](https://github.com/ddev/ddev-orthanc/actions/workflows/tests.yml/badge.svg)](https://github.com/ddev/ddev-orthanc/actions/workflows/tests.yml) ![project is maintained](https://img.shields.io/maintenance/yes/2024.svg)

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

**Contributed and maintained by [@madebydaniz](https://github.com/madebydaniz)**
