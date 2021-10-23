# Bodyfit Bot

## Steps explanation
- User go to a branch website, e.g. https://bodyfittraining.com/club/farrer-park/
- User click on timetable button. The timetable/login form is in an iframe: `https://clients.onefitstop.com/index.php?route=widget/directory/businessclass&trid=<TRID>`
- User click on login button: `https://clients.onefitstop.com/index.php?route=widget/directory/businessclass&trid=<TRID>=&login=true`
- Fill-in email and password. The login POST request is
  ```
  curl 'https://clients.onefitstop.com/login&loginAs=trainer' \
  --data-raw 'login=1\
  &email=<EMAIL>\
  &password=<PASSWORD>\
  &redirect=<ANYTHING>\
  &loginchek=businesspages
  &trid=<TRID>'
  ```
- Got the session in the cookies under key `PHPSESSID`. Can use this cookies for subsequence auth endpoints
- Back to the timetable screen: `https://clients.onefitstop.com/index.php?route=widget/directory/businessclass&trid=<TRID>&PHPSESSID=<PHPSESSID>`
- In each "Book Class" or "Join Waitlist" button there is a link.
  - Book Class:
    - follow the link
    - A form with all needed information to book the slot appear
    - Submit the form by clicking the button
    - It open a payment confirmation screen
    - Confirm again
  - Join Waitlist:
    - Is simpler just construct a POST request base on the URL in the "Join Waitlist" button and submit it.

## Release
```sh
docker build . -t seannguyen/bodyfit-bot

docker push seannguyen/bodyfit-bot
```
