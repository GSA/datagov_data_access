# README - TODO

## Contributing

See [CONTRIBUTING](CONTRIBUTING.md) for additional information.

## Public domain

This project is in the worldwide [public domain](LICENSE.md). As stated in [CONTRIBUTING](CONTRIBUTING.md):

> This project is in the public domain within the United States, and copyright and related rights in the work worldwide are waived through the [CC0 1.0 Universal public domain dedication](https://creativecommons.org/publicdomain/zero/1.0/).
>
> All contributions to this project will be released under the CC0 dedication. By submitting a pull request, you are agreeing to comply with this waiver of copyright interest.


## Release coordination with downstream apps
- harvester and catalog consume the data-access functionality in this repo which means updates here need to be 
integrated and deployed alongside application code changes in harvester and/or catalog otherwise something like
a database migration, which harvester manages, could break harvester if the application code isn't deployed to handle those db changes.
- currently, this process looks like...
  1. introduce change to data-access (PR)
  2. release that change.
  3. integrate that release into application code change branch
    - db migration typically only impacts harvester so harvester app code change is expected. following this merge, catalog needs to be updated with the new data-access update.
    - search, generally, impacts harvester and catalog which means intergration and deployment need to be coordinated carefully.
  4. submit PR with application code change alongside data-access update


## Local development and integration into consuming apps
- update consuming app data-access dependency to point to your local copy (or a remote branch)
- make change to data-access
  - run `poetry update datagov-data-access`
- make change to consuming app

## Deployment on development
- make changes to db and/or search on develop branch (hasn't been created yet)
- update consuming app dependency to point to develop branch of data-access
- make change to application code
- deploy to develop branch on remote.