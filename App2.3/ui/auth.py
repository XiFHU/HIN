# ui/auth.py

import streamlit as st
import pandas as pd
import hashlib
import os
from pathlib import Path


USERS_FILE = Path("auth/users.csv")
REQUESTS_FILE = Path("auth/access_requests.csv")


def is_localhost():
    try:
        host = st.context.headers.get("host", "")
        return (
            "localhost" in host
            or "127.0.0.1" in host
        )
    except Exception:
        return False


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def ensure_auth_files():
    os.makedirs("auth", exist_ok=True)

    if not USERS_FILE.exists():
        pd.DataFrame(
            columns=[
                "email",
                "password_hash",
                "approved"
            ]
        ).to_csv(USERS_FILE, index=False)

    if not REQUESTS_FILE.exists():
        pd.DataFrame(
            columns=[
                "name",
                "email",
                "reason",
                "approved"
            ]
        ).to_csv(REQUESTS_FILE, index=False)


def load_users():
    ensure_auth_files()
    return pd.read_csv(USERS_FILE)


def save_users(users):
    users.to_csv(USERS_FILE, index=False)


def load_requests():
    ensure_auth_files()
    return pd.read_csv(REQUESTS_FILE)


def save_requests(requests):
    requests.to_csv(REQUESTS_FILE, index=False)


def show_request_access_page():
    st.subheader("Request Access")

    name = st.text_input(
        "Name",
        key="request_name"
    )

    email = st.text_input(
        "Email",
        key="request_email"
    )

    reason = st.text_area(
        "Reason for access",
        key="request_reason"
    )

    if st.button("Submit Request"):
        if not name or not email:
            st.error("Please enter your name and email.")
            return

        requests = load_requests()

        if email in requests["email"].astype(str).values:
            st.info("You already submitted a request.")
            return

        new_request = pd.DataFrame(
            [{
                "name": name,
                "email": email,
                "reason": reason,
                "approved": False
            }]
        )

        requests = pd.concat(
            [requests, new_request],
            ignore_index=True
        )

        save_requests(requests)

        st.success("Request submitted. Please wait for approval.")


def show_login_page():
    st.title("HIN Tool Login")

    tab_login, tab_request = st.tabs(
        [
            "Login",
            "Request Access"
        ]
    )

    with tab_login:
        email = st.text_input(
            "Email",
            key="login_email"
        )

        password = st.text_input(
            "Password",
            type="password",
            key="login_password"
        )

        if st.button("Login"):
            users = load_users()

            password_hash = hash_password(password)

            matched = users[
                (users["email"].astype(str) == email)
                & (users["password_hash"].astype(str) == password_hash)
                & (users["approved"] == True)
            ]

            if not matched.empty:
                st.session_state["logged_in"] = True
                st.session_state["user_email"] = email
                st.rerun()
            else:
                st.error("Invalid login or account not approved.")

    with tab_request:
        show_request_access_page()


def show_admin_page():
    st.title("Admin Approval")

    admin_password = st.text_input(
        "Admin password",
        type="password"
    )

    if admin_password != st.secrets.get("ADMIN_PASSWORD", ""):
        st.stop()

    requests = load_requests()

    st.subheader("Access Requests")

    if requests.empty:
        st.info("No access requests.")
        return

    for idx, row in requests.iterrows():
        with st.expander(row["email"]):
            st.write("Name:", row["name"])
            st.write("Reason:", row["reason"])

            new_password = st.text_input(
                "Set temporary password",
                type="password",
                key=f"password_{idx}"
            )

            if st.button(
                "Approve User",
                key=f"approve_{idx}"
            ):
                if not new_password:
                    st.error("Please set a password first.")
                    return

                users = load_users()

                new_user = pd.DataFrame(
                    [{
                        "email": row["email"],
                        "password_hash": hash_password(new_password),
                        "approved": True
                    }]
                )

                users = users[
                    users["email"].astype(str) != str(row["email"])
                ]

                users = pd.concat(
                    [users, new_user],
                    ignore_index=True
                )

                save_users(users)

                requests.loc[idx, "approved"] = True
                save_requests(requests)

                st.success("User approved.")
                st.rerun()


def require_login():
    if is_localhost():
        return

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        show_login_page()
        st.stop()
