from calendar import weekday
from requests import post, get
import logging
from bs4 import BeautifulSoup
from datetime import datetime
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import os
from config import settings
import threading
from urllib.parse import urlparse, parse_qs
import sib_api_v3_sdk

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.getLevelName("INFO"),
)

logger = logging.getLogger(__name__)


SLOT_STATUS_PENDING = "SLOT_STATUS_PENDING"
SLOT_STATUS_BOOKED = "SLOT_STATUS_BOOKED"
SLOT_STATUS_WAITLISTABLE = "SLOT_STATUS_WAITLISTABLE"
SLOT_STATUS_WAITLISTED = "SLOT_STATUS_WAITLISTED"
SLOT_STATUS_FULL = "SLOT_STATUS_FULL"
SLOT_STATUS_FAILED = "SLOT_STATUS_FAILED"


class BodyfitBot:
    __cookie_domain = "onefitstop.com"
    __domain = "clients.onefitstop.com"
    __base_url = f"https://{__domain}"
    __email = settings.email
    __password = settings.password
    __trainer_id = settings.trainer_id
    __trid = settings.trid
    __email_api_instance = None
    __email_sender = None
    __email_sendTo = None

    def __init__(self) -> None:
        # Setup Email Notification
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key["api-key"] = settings.sendinblue_api_key

        # create an instance of the API class
        self.__email_api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )

        self.__email_sender = sib_api_v3_sdk.SendSmtpEmailSender(
            name="BFT Bot", email="bot@seannguyen.me"
        )
        self.__email_sendTo = sib_api_v3_sdk.SendSmtpEmailTo(
            name=settings.notification_email, email=settings.notification_email
        )

    def bookSlot(self):
        logger.info("Start booking slots")
        try:
            cookies = self.__login()
            result = self.__getAndBookSlots(cookies)
            logger.info(f"Result {result}")
            self.__send_success_email(result)
        except Exception as e:
            logger.error(e)
            self.__send_failure_email()

        logger.info("Finished booking slots")

    def __send_failure_email(self):
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            sender=self.__email_sender,
            to=[self.__email_sendTo],
            html_content=f"{datetime.datetime.today()} Something went wrong when booking BFT classes, please check manually",
            subject="Something went wrong when booking BFT classes",
        )

        self.__email_api_instance.send_transac_email(send_smtp_email)

    def __send_success_email(self, results):
        html_content = "<h3>Finished booking classes, here is the result</h3>"
        for result_slot in results:
            date_str = (
                result_slot["date"].strftime("%A, %B %d")
                if "date" in result_slot
                else result_slot["day_of_week"]
            )
            time_str = result_slot["time_of_day"]
            status_str = "Unknown, you might want to check this slot manually"
            if result_slot["state"] == SLOT_STATUS_PENDING:
                status_str = "Can't find this slot to book"
            elif result_slot["state"] == SLOT_STATUS_BOOKED:
                status_str = "Booked"
            elif result_slot["state"] == SLOT_STATUS_WAITLISTED:
                status_str = "Waitlisted"
            elif result_slot["state"] == SLOT_STATUS_FULL:
                status_str = "Fulled, unable to join waitlist"
            html_content += f"<p>{date_str} {time_str}: <b>{status_str}</b></p>"

        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            sender=self.__email_sender,
            to=[self.__email_sendTo],
            html_content=html_content,
            subject="Booking Result",
        )

        self.__email_api_instance.send_transac_email(send_smtp_email)

    def __login(self):
        resp = post(
            f"{self.__base_url}/login",
            params={"loginAs": "trainer"},
            data={
                "login": "1",
                "email": self.__email,
                "password": self.__password,
                "redirect": self.__base_url,
                "loginchek": "businesspages",
                "trid": self.__trid,
            },
            allow_redirects=False,
            timeout=30,
        )

        if resp.status_code >= 400:
            raise RuntimeError(
                f"Fail to login, status {resp.status_code}, resp {resp.text}"
            )

        logger.info("Successfully logged-in")
        return resp.cookies

    def __getAndBookSlots(self, cookies):
        desired_slots = self.__get_desired_slot()
        threads = list()
        page = 1
        while True:
            slots_at_page = self.__getSlotsAtPage(cookies, page)
            if slots_at_page is None:
                break

            for desired_slot in desired_slots:
                if desired_slot["state"] != SLOT_STATUS_PENDING:
                    continue
                if desired_slot["day_of_week"] in slots_at_page:
                    slots_at_day = slots_at_page[desired_slot["day_of_week"]]
                    if desired_slot["time_of_day"] in slots_at_day:
                        attempted_slot = slots_at_day[desired_slot["time_of_day"]]
                        t = threading.Thread(
                            target=self.__attemptBook,
                            args=(cookies, desired_slot, attempted_slot),
                        )
                        threads.append(t)
                        t.start()
            page += 1

        for t in threads:
            t.join(60)
        return desired_slots

    def __getSlotsAtPage(self, cookies, page):
        logger.info(f"Start fetch slots information from html page {page}")
        resp = get(
            f"{self.__base_url}/index.php?route=widget/directory/businessclass&trid={self.__trid}&mytrainer_id={self.__trainer_id}",
            params={
                "trid": self.__trid,
                "mytrainer_id": self.__trainer_id,
                "page": page,
            },
            cookies=cookies,
            timeout=30,
        )

        if resp.status_code >= 400:
            raise RuntimeError(
                f"Fail to get html list of slots, status {resp.status_code}, resp {resp.text}"
            )

        soup = BeautifulSoup(resp.text, "lxml")

        if soup.find(text=re.compile(".*No Class scheduled.*")):
            return None

        day_schedules = soup.select(".schedule-list > ul > li:not(.schedule-list-head)")

        slots_by_weekday = {}
        for day_schedule in day_schedules:
            date_str = day_schedule.select_one(".schedule-list-day").text
            slot_date = datetime.strptime(date_str, "%A, %B %d, %Y")
            weekday_key = slot_date.strftime("%a")
            if weekday_key not in slots_by_weekday:
                slots_by_weekday[weekday_key] = {}
            slots = day_schedule.select(".schedule")
            for slot in slots:
                slot_state = SLOT_STATUS_PENDING
                if slot.find("p", text=re.compile(".*Booked.*")):
                    slot_state = SLOT_STATUS_BOOKED
                elif slot.find("span", text="Class Full"):
                    slot_state = SLOT_STATUS_FULL
                elif slot.find("span", text="Already in waitlist"):
                    slot_state = SLOT_STATUS_WAITLISTED

                book_class_button = slot.select_one("button.bookClass")
                book_class_url = None
                if book_class_button:
                    onclick_content = book_class_button["onclick"]
                    m = re.search("'(https.*)'", onclick_content)
                    book_class_url = m.group(1)
                join_waitlist_button = slot.select_one("button.join_wait_list")
                join_waitlist_url = None
                if join_waitlist_button:
                    join_waitlist_url = join_waitlist_button["data-purl"]
                    slot_state = SLOT_STATUS_WAITLISTABLE

                time_str = slot.select_one(":first-child").text.split("to")[0]
                time_str = time_str.strip()
                slot_time = datetime.strptime(time_str, "%I:%M %p")
                slots_by_weekday[weekday_key][slot_time.strftime("%H:%M")] = {
                    "state": slot_state,
                    "book_class_url": book_class_url,
                    "join_waitlist_url": join_waitlist_url,
                    "date": slot_date,
                }
        logger.info(f"Success parse slots information from html page {page}")
        return slots_by_weekday

    def __attemptBook(self, cookies, desired_slot, attempted_slot):
        logger.info(
            f"Processing desired slot day of week: {desired_slot['day_of_week']} time of day: {desired_slot['time_of_day']}"
        )
        try:
            desired_slot["date"] = attempted_slot["date"]
            if attempted_slot["state"] == SLOT_STATUS_PENDING:
                self.__book_available_slot(cookies, desired_slot, attempted_slot)
                return
            if attempted_slot["state"] == SLOT_STATUS_WAITLISTABLE:
                self.__join_waitlist(cookies, desired_slot, attempted_slot)
                return
            if attempted_slot["state"] != SLOT_STATUS_PENDING:
                desired_slot["state"] = attempted_slot["state"]
                logger.info(
                    f"Result booking slot day of week: {desired_slot['day_of_week']} time of day: {desired_slot['time_of_day']}, state: {desired_slot['state']}"
                )
                return

        except Exception as e:
            desired_slot["state"] = SLOT_STATUS_FAILED
            raise e

    def __book_available_slot(self, cookies, desired_slot, attempted_slot):
        driver = self.__prepare_chrome_driver()
        wait = WebDriverWait(driver, 10)

        driver.get("https://clients.onefitstop.com")
        driver.add_cookie(
            {
                "name": "PHPSESSID",
                "value": cookies["PHPSESSID"],
                "domain": self.__cookie_domain,
            }
        )

        driver.get(attempted_slot["book_class_url"])
        make_reservation_button = wait.until(
            EC.element_to_be_clickable((By.ID, "singleeventpayment"))
        )
        make_reservation_button.click()

        make_payment_button = wait.until(
            EC.element_to_be_clickable((By.ID, "btn_payment_bycredits"))
        )
        make_payment_button.click()
        driver.quit()
        desired_slot["state"] = SLOT_STATUS_BOOKED
        logger.info(
            f"Booked slot day of week: {desired_slot['day_of_week']} time of day: {desired_slot['time_of_day']}, state: {desired_slot['state']}"
        )

    def __join_waitlist(self, cookies, desired_slot, attempted_slot):
        waitlist_url = urlparse(attempted_slot["join_waitlist_url"])
        waitlist_url_query = parse_qs(waitlist_url.query)

        resp = post(
            f"{self.__base_url}/index.php?route=directory/directory/widgetjoinwaitlist&PHPSESSID=l7r83ftt7am7diqua8r86q9ll0",
            params={
                "route": "directory/directory/widgetjoinwaitlist",
                "PHPSESSID": "l7r83ftt7am7diqua8r86q9ll0",
            },
            data={
                "eid": waitlist_url_query["eid"][0],
                "dirId": None,
                "bstd": waitlist_url_query["bstd"][0],
                "bookingfrom": "widget/directory/",
                "joinwailist": "joinwailistYes",
                "latecancelwaitlist": "movetowaitlist",
                "bid": None,
            },
            allow_redirects=False,
            cookies=cookies,
            timeout=30,
        )

        if resp.status_code >= 400:
            raise RuntimeError(
                f"Fail to join waitlist, status {resp.status_code}, resp {resp.text}"
            )

        desired_slot["state"] = SLOT_STATUS_WAITLISTED
        logger.info(
            f"Joined waitlist slot day of week: {desired_slot['day_of_week']} time of day: {desired_slot['time_of_day']}, state: {desired_slot['state']}"
        )

    def __prepare_chrome_driver(self):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-notifications")
        options.add_argument("--window-size=1280,800")
        options.add_argument("--disable-gpu")
        # Need to set user agent to look normal, otherwise Soxo will show a worning
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
        )

        service = Service(os.getcwd() + "/bin_lib/chromedriver")
        driver = webdriver.Chrome(options=options, service=service)
        driver.implicitly_wait(1)
        return driver

    def __get_desired_slot(self):
        return list(
            map(
                lambda i: {
                    "day_of_week": i.day_of_week,
                    "time_of_day": i.time_of_day,
                    "state": SLOT_STATUS_PENDING,
                },
                settings.desired_slots,
            )
        )


if __name__ == "__main__":
    bodyfitBot = BodyfitBot()
    bodyfitBot.bookSlot()
