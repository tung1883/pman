DOCKER.ENGINE-SECURITY-HTTPS-README(1) Sandbox manual DOCKER.ENGINE-SECURITY-HTTPS-README(1)

       NAME

       README - This is an initial attempt to make it easier to test the TLS (HTTPS) examples in the protect-access.md

       README

       This is an initial attempt to make it easier to test the TLS (HTTPS) examples in the protect-access.md doc.

       At this point, it is a manual thing, and I've been running it in boot2docker.

       My process is as following:

       $ boot2docker ssh root@boot2docker:/# git clone https://github.com/moby/moby root@boot2docker:/# cd docker/docs/articles/https root@boot2docker:/# make cert

       lots of things to see and manually answer, as openssl wants to be interactive

       root@boot2docker:/# sudo make run

       Start another terminal:

       $ boot2docker ssh root@boot2docker:/# cd docker/docs/articles/https root@boot2docker:/# make client

       The last connects first with --tls and then with --tlsverify, both should succeed.

Docker manual                           from the official documentation
